import asyncio
import json
from types import SimpleNamespace

import pytest

from cloud.gateways import MAX_READERS, GatewayHub

READER = {
    'id': 'rd-3',
    'address': '10.10.0.4',
    'since': '2026-11-15T12:00:00+00:00',
    'key_exchange': 'X25519',
}


class GatewayConnection:
    """A gateway's connection to the cloud: sends `messages`, then stays open
    until close()."""

    def __init__(self, gateway_id, messages):
        self.request = SimpleNamespace(headers={'Gateway-Id': gateway_id})
        self.remote_address = ('172.18.0.4', 50000)
        self.transport = SimpleNamespace(get_extra_info={'ssl_object': None}.get)
        self.messages = [json.dumps(message) for message in messages]
        self.sent = []
        self.closed = asyncio.Event()

    def close(self):
        self.closed.set()

    async def __aiter__(self):
        for message in self.messages:
            yield message
        await self.closed.wait()

    async def send(self, message):
        self.sent.append(json.loads(message))


def readers_report(readers, request_id='r1'):
    return {'type': 'readers', 'readers': readers, 'request_id': request_id}


async def test_answers_with_the_request_id(db):
    hub = GatewayHub(db)

    reply = await hub.respond(
        {'id': 'key-bob', 'reader_id': 'rd-3', 'request_id': 'r1'}, 'gw-1'
    )

    assert reply == {'request_id': 'r1', 'result': 'pass'}


async def test_logs_the_gateway_the_request_came_through(db):
    await GatewayHub(db).respond({'id': 'key-bob', 'reader_id': 'rd-4'}, 'gw-7')

    [event] = db.events()
    assert (event['gateway_id'], event['result']) == ('gw-7', 'fail')


@pytest.mark.parametrize(
    'request_body',
    [
        {'request_id': 'r1'},
        {'request_id': 'r1', 'id': 'key-bob'},
        {'request_id': 'r1', 'id': 42, 'reader_id': 'rd-1'},
    ],
)
async def test_invalid_request_fails_without_logging(db, request_body):
    reply = await GatewayHub(db).respond(request_body, 'gw-1')

    assert reply == {'request_id': 'r1', 'result': 'fail'}
    assert db.events() == []


async def test_lists_the_readers_a_gateway_reports(db, wait_until):
    hub = GatewayHub(db)
    ws = GatewayConnection('gw-1', [readers_report([READER])])
    task = asyncio.create_task(hub.handle(ws))
    await wait_until(lambda: ws.sent)

    [gateway] = hub.connected()
    ws.close()
    await task

    assert ws.sent == [{'request_id': 'r1', 'result': 'ok'}]
    assert gateway['readers'] == [{**READER, 'post_quantum': False}]
    assert db.events() == []  # a reader list is no access event


async def test_readers_are_unknown_until_the_gateway_reports(db, wait_until):
    # e.g. a gateway from before reader lists
    hub = GatewayHub(db)
    ws = GatewayConnection('gw-1', [])
    task = asyncio.create_task(hub.handle(ws))
    await wait_until(hub.connected)

    [gateway] = hub.connected()
    ws.close()
    await task

    assert gateway['readers'] is None


async def test_the_latest_report_counts_and_an_empty_one_means_none(db, wait_until):
    hub = GatewayHub(db)
    ws = GatewayConnection(
        'gw-1', [readers_report([READER], 'r1'), readers_report([], 'r2')]
    )
    task = asyncio.create_task(hub.handle(ws))
    await wait_until(lambda: len(ws.sent) == 2)

    [gateway] = hub.connected()
    ws.close()
    await task

    assert gateway['readers'] == []


async def test_readers_are_forgotten_when_their_gateway_disconnects(db, wait_until):
    hub = GatewayHub(db)
    first = GatewayConnection('gw-1', [readers_report([READER])])
    task = asyncio.create_task(hub.handle(first))
    await wait_until(lambda: first.sent)
    first.close()
    await task

    again = GatewayConnection('gw-1', [])
    task = asyncio.create_task(hub.handle(again))
    await wait_until(hub.connected)
    [gateway] = hub.connected()
    again.close()
    await task

    assert gateway['readers'] is None


async def test_keeps_only_the_known_string_fields_of_each_reader(db):
    hub = GatewayHub(db)
    reported = {'id': 'rd-9', 'address': 7, 'since': None, 'zone': 'x', 'extra': [1]}

    reply = await hub.respond(readers_report([reported]), 'gw-1')

    assert reply['result'] == 'ok'
    assert hub._readers['gw-1'] == [  # pylint: disable=protected-access
        {
            'id': 'rd-9',
            'address': None,
            'since': None,
            'key_exchange': None,
            'post_quantum': None,
        }
    ]


@pytest.mark.parametrize(
    'readers',
    [
        None,
        'rd-1',
        {'id': 'rd-1'},
        ['rd-1'],
        [{'address': '10.10.0.2'}],
        [{'id': 42}],
        [{'id': f'rd-{n}'} for n in range(MAX_READERS + 1)],
    ],
)
async def test_malformed_reader_list_fails_and_changes_nothing(db, readers):
    hub = GatewayHub(db)
    await hub.respond(readers_report([READER]), 'gw-1')

    reply = await hub.respond(readers_report(readers, 'r2'), 'gw-1')

    assert reply == {'request_id': 'r2', 'result': 'fail'}
    assert [r['id'] for r in hub._readers['gw-1']] == ['rd-3']  # pylint: disable=protected-access
    assert db.events() == []
