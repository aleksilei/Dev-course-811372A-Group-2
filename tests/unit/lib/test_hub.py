import json
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from lib import tls
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
    def __init__(self, headers, messages, group=None):
        self.request = SimpleNamespace(headers=headers)
        self.remote_address = ('10.0.0.5', 50000)
        # A plain connection, or TLS with an SSLObject that reports its group
        # like Python 3.15's does.
        ssl_object = group and SimpleNamespace(group=lambda: group)
        self.transport = SimpleNamespace(get_extra_info={'ssl_object': ssl_object}.get)
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
        [
            {
                'id': 'rd-1',
                'address': '10.0.0.5',
                'since': ANY,
                'key_exchange': None,
                'post_quantum': None,
            }
        ]
    ]
    assert hub.connected() == []


async def test_lists_the_key_exchange_of_each_client():
    hub = EchoHub()

    await hub.handle(FakeConnection({'Test-Id': 'gw-1'}, ['{}'], 'X25519MLKEM768'))

    [listed] = hub.connected_during_request[0]
    assert (listed['key_exchange'], listed['post_quantum']) == ('X25519MLKEM768', True)


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
