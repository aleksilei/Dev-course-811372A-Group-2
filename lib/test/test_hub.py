import json
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from lib.hub import Hub


class EchoHub(Hub):
    id_header = 'Test-Id'

    def __init__(self):
        super().__init__()
        self.connected_during_request = []

    async def respond(self, request, client_id):
        self.connected_during_request.append(self.connected())
        return {'echo': request, 'from': client_id}


class FakeConnection:
    def __init__(self, headers, messages):
        self.request = SimpleNamespace(headers=headers)
        self.remote_address = ('10.0.0.5', 50000)
        self.messages = messages
        self.sent = []

    async def __aiter__(self):
        for message in self.messages:
            yield message

    async def send(self, message):
        self.sent.append(json.loads(message))


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
        [{'id': 'rd-1', 'address': '10.0.0.5', 'since': ANY}]
    ]
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
