import contextlib
import json
import logging

import pytest
from websockets.asyncio.server import serve

from reader.scanner import GatewayClient, scan


def gateway_passing(key_uuid):
    """A fake gateway handler that only lets `key_uuid` through at rd-1."""

    async def handler(ws):
        async for message in ws:
            passed = json.loads(message) == {'id': key_uuid, 'reader_id': 'rd-1'}
            await ws.send(json.dumps({'result': 'pass' if passed else 'fail'}))

    return handler


@contextlib.asynccontextmanager
async def client_of(gateway_handler, timeout=5.0):
    async with serve(gateway_handler, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = GatewayClient(f'ws://127.0.0.1:{port}', 'rd-1', None, timeout)
        try:
            yield client
        finally:
            await client.close()


async def test_authorize_follows_the_gateway_answer():
    async with client_of(gateway_passing('key-alice')) as client:
        assert await client.authorize('key-alice') is True
        assert await client.authorize('key-mallory') is False


async def test_sends_its_reader_id_on_connect():
    seen = []

    async def gateway(ws):
        seen.append(ws.request.headers['Reader-Id'])
        await gateway_passing('key-alice')(ws)

    async with client_of(gateway) as client:
        await client.authorize('key-alice')

    assert seen == ['rd-1']


async def test_fails_closed_when_gateway_is_unreachable():
    client = GatewayClient('ws://127.0.0.1:1', 'rd-1', None, timeout=1)

    assert await client.authorize('key-alice') is False


async def test_fails_closed_when_gateway_does_not_answer():
    async def silent_gateway(ws):
        await ws.wait_closed()

    async with client_of(silent_gateway, timeout=0.1) as client:
        assert await client.authorize('key-alice') is False


@pytest.mark.parametrize(
    'reply',
    ['not json', '"pass"', '["pass"]', '{}', '{"result": "PASS"}', '{"result": true}'],
)
async def test_fails_closed_on_anything_but_an_explicit_pass(reply):
    async def gateway(ws):
        async for _ in ws:
            await ws.send(reply)

    async with client_of(gateway) as client:
        assert await client.authorize('key-alice') is False


async def test_reconnects_after_a_failure():
    connections = []

    async def gateway_dropping_first_connection(ws):
        connections.append(ws)
        if len(connections) > 1:
            await gateway_passing('key-alice')(ws)

    async with client_of(gateway_dropping_first_connection) as client:
        assert await client.authorize('key-alice') is False
        assert await client.authorize('key-alice') is True


class StubClient:
    reader_id = 'rd-1'

    def __init__(self, granted):
        self.granted = granted

    async def authorize(self, _key_uuid):
        return self.granted


@pytest.mark.parametrize(('granted', 'outcome'), [(True, 'PASS'), (False, 'FAIL')])
async def test_scan_logs_the_outcome_and_unlocks_only_on_pass(caplog, granted, outcome):
    caplog.set_level(logging.INFO)

    assert await scan(StubClient(granted), 'key-alice', 'front-door') is granted

    assert f'{outcome} key=key-alice reader=rd-1 zone=front-door' in caplog.text
    assert ('UNLOCK front-door' in caplog.text) is granted
