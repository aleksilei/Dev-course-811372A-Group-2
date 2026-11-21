import asyncio
import json
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosedError

from cloud.gateways import GatewayHub
from lib import openssl, tls
from lib.hub import Hub


class EchoHub(Hub):
    id_header = 'Test-Id'

    def __init__(self):
        super().__init__()
        self.connected_during_request = []

    async def respond(self, request, client_id):
        self.connected_during_request.append(self.connected())
        return {'echo': request, 'from': client_id}


class ChangeHub(EchoHub):
    """Records the connected client IDs every time changed() is called."""

    def __init__(self):
        super().__init__()
        self.changes = []

    def changed(self):
        self.changes.append([client['id'] for client in self.connected()])


class FakeConnection:
    def __init__(self, headers, messages, group=None):
        self.request = SimpleNamespace(headers=headers)
        self.remote_address = ('10.0.0.5', 50000)
        # A plain connection, or TLS with an SSLObject that reports its group
        # like Python 3.15's does.
        ssl_object = group and SimpleNamespace(
            group=lambda: group,
            version=lambda: 'TLSv1.3',
            cipher=lambda: ('TLS_AES_256_GCM_SHA384', 'TLSv1.3', 256),
        )
        self.transport = SimpleNamespace(get_extra_info={'ssl_object': ssl_object}.get)
        self.messages = messages
        self.sent = []

    async def __aiter__(self):
        for message in self.messages:
            yield message

    async def send(self, message):
        self.sent.append(json.loads(message))


class OpenConnection(FakeConnection):
    """Stays open, without sending anything, until close() is called."""

    def __init__(self, headers, address):
        super().__init__(headers, [])
        self.remote_address = (address, 50000)
        self.closed = asyncio.Event()

    def close(self):
        self.closed.set()

    async def __aiter__(self):
        await self.closed.wait()
        for message in self.messages:
            yield message


class HangingUpConnection(FakeConnection):
    """A client that disconnects before its reply is sent."""

    async def send(self, message):
        raise ConnectionClosedError(None, None)


async def test_gateway_logs_each_connections_tls_during_overlapping_reconnect(
    db, wait_until
):
    release = asyncio.Event()

    class DelayedConnection(FakeConnection):
        async def __aiter__(self):
            await release.wait()
            async for message in super().__aiter__():
                yield message

    hub = GatewayHub(db)
    hub.openssl_version = 'OpenSSL 3.5.9'
    old_headers = {'Gateway-Id': 'gw-1', 'OpenSSL-Version': 'OpenSSL 3.5.6'}
    new_headers = {'Gateway-Id': 'gw-1', 'OpenSSL-Version': 'OpenSSL 3.5.7'}
    messages = ['{"id": "key-alice", "reader_id": "rd-1"}']
    old = asyncio.create_task(
        hub.handle(DelayedConnection(old_headers, messages, 'X25519MLKEM768'))
    )
    await wait_until(hub.connected)
    await hub.handle(FakeConnection(new_headers, messages, 'X25519MLKEM768'))
    release.set()
    await old

    counts = db.event_counts_since('2000-01-01', '2100-01-01')
    assert {
        (row['key_exchange'], row['gateway_openssl']): row['count'] for row in counts
    } == {
        ('X25519MLKEM768', 'OpenSSL 3.5.6'): 1,
        ('X25519MLKEM768', 'OpenSSL 3.5.7'): 1,
    }
    assert {row['cloud_openssl'] for row in counts} == {'OpenSSL 3.5.9'}
    assert hub.request_link() == {}


async def test_answers_every_request_with_respond():
    ws = FakeConnection({'Test-Id': 'rd-1'}, ['{"a": 1}', '{"b": 2}'])

    await EchoHub().handle(ws)

    assert ws.sent == [
        {'echo': {'a': 1}, 'from': 'rd-1'},
        {'echo': {'b': 2}, 'from': 'rd-1'},
    ]


async def test_client_is_listed_only_while_connected():
    hub = EchoHub()

    await hub.handle(FakeConnection({'Test-Id': 'rd-1'}, ['{}']))

    assert hub.connected_during_request == [
        [
            {
                'id': 'rd-1',
                'address': '10.0.0.5',
                'since': ANY,
                'tls_version': None,
                'cipher': None,
                'key_exchange': None,
                'post_quantum': None,
                # It reported no OpenSSL version: assumed vulnerable.
                **openssl.details(None),
            }
        ]
    ]
    assert hub.connected() == []


async def test_lists_the_key_exchange_of_each_client():
    hub = EchoHub()

    await hub.handle(FakeConnection({'Test-Id': 'gw-1'}, ['{}'], 'X25519MLKEM768'))

    [listed] = hub.connected_during_request[0]
    assert (listed['key_exchange'], listed['post_quantum']) == ('X25519MLKEM768', True)
    assert (listed['tls_version'], listed['cipher']) == (
        'TLSv1.3',
        'TLS_AES_256_GCM_SHA384',
    )


async def test_lists_the_openssl_version_each_client_reports():
    hub = EchoHub()
    headers = {'Test-Id': 'gw-1', 'OpenSSL-Version': 'OpenSSL 3.5.6'}

    await hub.handle(FakeConnection(headers, ['{}']))

    [listed] = hub.connected_during_request[0]
    assert listed['openssl'] == 'OpenSSL 3.5.6'
    assert listed['openssl_vulnerable'] is True
    assert listed['openssl_advisory']


async def test_a_malformed_openssl_version_is_assumed_vulnerable():
    hub = EchoHub()
    headers = {'Test-Id': 'gw-1', 'OpenSSL-Version': 'OpenSSL 3.5.7' + ' ' * 100}

    await hub.handle(FakeConnection(headers, ['{}']))

    [listed] = hub.connected_during_request[0]
    assert (listed['openssl'], listed['openssl_checked']) == (None, False)
    assert listed['openssl_vulnerable'] is True


async def test_reconnected_client_stays_listed_when_its_old_connection_closes(
    wait_until,
):
    # A gateway can reconnect before the cloud notices its old connection died.
    hub = EchoHub()
    old = OpenConnection({'Test-Id': 'gw-1'}, '10.0.0.1')
    new = OpenConnection({'Test-Id': 'gw-1'}, '10.0.0.2')
    old_task = asyncio.create_task(hub.handle(old))
    await wait_until(hub.connected)
    new_task = asyncio.create_task(hub.handle(new))
    await wait_until(lambda: hub.connected()[0]['address'] == '10.0.0.2')

    old.close()
    await old_task

    assert [client['address'] for client in hub.connected()] == ['10.0.0.2']
    new.close()
    await new_task
    assert hub.connected() == []


async def test_changed_is_called_when_a_client_connects_and_disconnects():
    hub = ChangeHub()

    await hub.handle(FakeConnection({'Test-Id': 'rd-1'}, ['{}']))

    assert hub.changes == [['rd-1'], []]


async def test_closing_a_replaced_connection_is_no_change(wait_until):
    hub = ChangeHub()
    old = OpenConnection({'Test-Id': 'gw-1'}, '10.0.0.1')
    new = OpenConnection({'Test-Id': 'gw-1'}, '10.0.0.2')
    old_task = asyncio.create_task(hub.handle(old))
    await wait_until(hub.connected)
    new_task = asyncio.create_task(hub.handle(new))
    await wait_until(lambda: len(hub.changes) == 2)

    old.close()
    await old_task
    assert hub.changes == [['gw-1'], ['gw-1']]

    new.close()
    await new_task
    assert hub.changes == [['gw-1'], ['gw-1'], []]


async def test_client_hanging_up_before_its_reply_is_unlisted():
    hub = EchoHub()

    await hub.handle(HangingUpConnection({'Test-Id': 'rd-1'}, ['{}']))

    assert hub.connected() == []


async def test_client_without_id_header_is_unknown():
    ws = FakeConnection({}, ['{}'])

    await EchoHub().handle(ws)

    assert ws.sent[0]['from'] == 'unknown'


@pytest.mark.parametrize('message', ['not json', '[1, 2]', '"text"'])
async def test_malformed_request_fails(message):
    ws = FakeConnection({'Test-Id': 'rd-1'}, [message])

    await EchoHub().handle(ws)

    assert ws.sent == [{'result': 'fail'}]


async def test_over_a_real_websocket():
    async with serve(EchoHub().handle, '127.0.0.1', 0) as server:
        uri = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        async with connect(uri, additional_headers={'Test-Id': 'gw-9'}) as ws:
            await ws.send('{"x": 1}')

            assert json.loads(await ws.recv()) == {'echo': {'x': 1}, 'from': 'gw-9'}


async def test_over_tls_lists_the_negotiated_group(certs):
    hub = EchoHub()
    server_context = tls.server_context(certs.cert, certs.key, tls.READER_GATEWAY)
    async with serve(hub.handle, '127.0.0.1', 0, ssl=server_context) as server:
        uri = f'wss://localhost:{server.sockets[0].getsockname()[1]}'
        async with connect(
            uri,
            ssl=tls.client_context(certs.ca, tls.READER_GATEWAY),
            additional_headers={'Test-Id': 'rd-1'},
        ) as ws:
            await ws.send('{}')
            await ws.recv()

    [listed] = hub.connected_during_request[0]
    assert (listed['key_exchange'], listed['post_quantum']) == ('X25519', False)
    assert listed['tls_version'] == 'TLSv1.3'
    assert listed['cipher'].startswith('TLS_')
