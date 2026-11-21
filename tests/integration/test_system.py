"""End-to-end: readers -> gateway -> cloud over TLS, wired as in each __main__."""

import asyncio
import contextlib
import json
import ssl
import threading
import urllib.request
from types import SimpleNamespace

import pytest
from websockets.asyncio.server import serve

from cloud.gateways import GatewayHub
from cloud.panel import PanelServer
from gateway.cloud_link import CloudLink
from gateway.readers import ReaderHub
from lib import tls
from reader.scanner import GatewayClient

ACCESS = [
    ('rd-1', 'key-alice', True),
    ('rd-2', 'key-carol', True),
    ('rd-3', 'key-bob', True),
    ('rd-3', 'key-alice', False),
    ('rd-4', 'key-carol', True),
    ('rd-4', 'key-bob', False),
    ('rd-1', 'key-mallory', False),
]


@pytest.fixture(name='running_system')
def running_system_fixture(certs, db, wait_until):
    """`async with running_system() as system` starts cloud, panel and gateway."""

    def port(server):
        return server.sockets[0].getsockname()[1]

    @contextlib.asynccontextmanager
    async def start():
        gateways = GatewayHub(db)
        panel = PanelServer(
            ('127.0.0.1', 0),
            tls.server_context(certs.cert, certs.key, tls.ADMIN_CLOUD),
            db,
            gateways,
        )
        threading.Thread(
            target=panel.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True
        ).start()
        cloud_context = tls.server_context(certs.cert, certs.key, tls.gateway_cloud())
        gateway_context = tls.server_context(certs.cert, certs.key, tls.READER_GATEWAY)

        async with serve(gateways.handle, '127.0.0.1', 0, ssl=cloud_context) as cloud:
            link = CloudLink(
                f'wss://localhost:{port(cloud)}',
                'gw-1',
                tls.client_context(certs.ca, tls.gateway_cloud()),
                retry_delay=0.05,
            )
            link_task = asyncio.create_task(link.run())
            readers = ReaderHub(link)
            async with serve(
                readers.handle, '127.0.0.1', 0, ssl=gateway_context
            ) as gateway:
                await wait_until(lambda: link.connected)

                def reader(reader_id):
                    return GatewayClient(
                        f'wss://localhost:{port(gateway)}',
                        reader_id,
                        tls.client_context(certs.ca, tls.READER_GATEWAY),
                    )

                def panel_api(path):
                    url = f'https://localhost:{panel.server_address[1]}/api/{path}'
                    context = tls.client_context(certs.ca, tls.ADMIN_CLOUD)
                    with urllib.request.urlopen(url, context=context) as response:
                        return json.loads(response.read())

                try:
                    yield SimpleNamespace(
                        cloud=cloud, link=link, reader=reader, panel_api=panel_api
                    )
                finally:
                    link_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await link_task
                    panel.shutdown()
                    panel.server_close()

    return start


@pytest.mark.parametrize(('reader_id', 'key_uuid', 'granted'), ACCESS)
async def test_access_decision(running_system, reader_id, key_uuid, granted):
    async with running_system() as system:
        reader = system.reader(reader_id)

        assert await reader.authorize(key_uuid) is granted

        await reader.close()


async def test_concurrent_readers_share_one_gateway(running_system):
    async with running_system() as system:
        readers = [system.reader(reader_id) for reader_id, _, _ in ACCESS * 5]
        keys = [key_uuid for _, key_uuid, _ in ACCESS * 5]

        results = await asyncio.gather(
            *(reader.authorize(key) for reader, key in zip(readers, keys))
        )

        assert results == [granted for _, _, granted in ACCESS * 5]
        await asyncio.gather(*(reader.close() for reader in readers))


async def test_panel_shows_the_event_and_the_connected_gateway(running_system):
    async with running_system() as system:
        reader = system.reader('rd-3')
        await reader.authorize('key-bob')
        await reader.close()

        [event] = await asyncio.to_thread(system.panel_api, 'events?reader=rd-3')
        gateways = await asyncio.to_thread(system.panel_api, 'gateways')

    assert event['key_uuid'] == 'key-bob'
    assert event['zone_name'] == 'server-room'
    assert event['gateway_id'] == 'gw-1'
    assert event['result'] == 'pass'
    [gateway] = gateways
    assert gateway['id'] == 'gw-1'
    # Whichever group this process's OpenSSL config picks; test_tls covers which.
    assert gateway['key_exchange'] is not None
    assert gateway['post_quantum'] == tls.is_post_quantum(gateway['key_exchange'])


async def test_panel_lists_the_readers_connected_to_each_gateway(
    running_system, wait_until
):
    def readers_of_gw_1():
        [gateway] = system.panel_api('gateways')
        return [reader['id'] for reader in gateway['readers']]

    async with running_system() as system:
        await wait_until(lambda: readers_of_gw_1() == [])
        rd1, rd3 = system.reader('rd-1'), system.reader('rd-3')
        await rd1.authorize('key-alice')
        await rd3.authorize('key-bob')
        await wait_until(lambda: readers_of_gw_1() == ['rd-1', 'rd-3'])
        [gateway] = await asyncio.to_thread(system.panel_api, 'gateways')

        await rd1.close()
        await wait_until(lambda: readers_of_gw_1() == ['rd-3'])
        await rd3.close()

    [listed, _] = gateway['readers']
    assert listed['key_exchange'] == 'X25519'
    assert listed['post_quantum'] is False
    assert listed['address'] == '127.0.0.1'


async def test_devices_api_shows_the_encryption_of_every_link(
    running_system, wait_until
):
    def rd3():
        rows = system.panel_api('devices')['devices']
        return next(row for row in rows if row['id'] == 'rd-3')

    async with running_system() as system:
        reader = system.reader('rd-3')
        await reader.authorize('key-bob')
        await wait_until(lambda: rd3()['state'] == 'connected')
        row = await asyncio.to_thread(rd3)
        await reader.close()

    own, upstream = row['links']
    assert (own['name'], own['key_exchange'], own['tls_version']) == (
        'reader → gateway',
        'X25519',
        'TLSv1.3',
    )
    assert own['cipher'].startswith('TLS_')
    assert (upstream['name'], upstream['tls_version']) == ('gateway → cloud', 'TLSv1.3')
    # The reader hop is classical, so the reader is too.
    assert row['status'] == 'classical'


async def test_readers_fail_closed_when_the_cloud_goes_down(running_system, wait_until):
    async with running_system() as system:
        reader = system.reader('rd-1')
        assert await reader.authorize('key-alice') is True

        system.cloud.close()
        await wait_until(lambda: not system.link.connected)

        assert await reader.authorize('key-alice') is False
        await reader.close()


@pytest.mark.parametrize(
    'case',  # (key exchange mode, reported OpenSSL, expected readiness)
    [
        ('hybrid', 'OpenSSL 3.5.8', 1.0),
        ('hybrid', 'OpenSSL 3.5.7', 0.0),
        ('classical', 'OpenSSL 3.5.8', 0.0),
    ],
)
async def test_readiness_uses_recorded_tls_after_gateway_disconnects(
    running_system, wait_until, monkeypatch, case
):
    mode, version, expected = case
    monkeypatch.setenv('KEY_EXCHANGE', mode)
    monkeypatch.setattr(ssl, 'OPENSSL_VERSION', version)
    async with running_system() as system:
        reader = system.reader('rd-1')
        assert await reader.authorize('key-alice') is True
        await reader.close()

        before = await asyncio.to_thread(system.panel_api, 'summary')
        assert before['readiness'] == expected
        assert before['recent_events'] == 1

        system.cloud.close()
        await wait_until(lambda: not system.link.connected)

        after = await asyncio.to_thread(system.panel_api, 'summary')
        assert after['gateways']['connected'] == 0
        assert after['readiness'] == expected
        assert after['non_pqc_traffic_share'] == 1 - expected
