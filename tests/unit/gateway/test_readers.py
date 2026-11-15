import asyncio
import json
from types import SimpleNamespace

import pytest

from gateway.readers import ReaderHub


class StubCloud:
    def __init__(self, reply=None):
        self.reply = reply
        self.requests = []
        self.reports = []

    async def request(self, request):
        self.requests.append(request)
        return self.reply

    def report_readers(self, readers):
        self.reports.append(readers)


class ReaderConnection:
    """A reader's connection to the gateway; stays open until close()."""

    def __init__(self, reader_id, address):
        self.request = SimpleNamespace(headers={'Reader-Id': reader_id})
        self.remote_address = (address, 50000)
        self.transport = SimpleNamespace(get_extra_info={'ssl_object': None}.get)
        self.closed = asyncio.Event()

    def close(self):
        self.closed.set()

    async def __aiter__(self):
        await self.closed.wait()
        for message in ():  # sends nothing
            yield message

    async def send(self, message):
        json.loads(message)


async def test_forwards_the_request_unchanged():
    cloud = StubCloud({'result': 'pass'})

    await ReaderHub(cloud).respond({'id': 'key-bob', 'reader_id': 'rd-3'}, 'rd-3')

    assert cloud.requests == [{'id': 'key-bob', 'reader_id': 'rd-3'}]


@pytest.mark.parametrize(
    ('cloud_reply', 'expected'),
    [
        ({'result': 'pass', 'request_id': 'r1'}, 'pass'),
        ({'result': 'fail', 'request_id': 'r1'}, 'fail'),
        ({'result': 'PASS'}, 'fail'),
        ({'result': True}, 'fail'),
        ({}, 'fail'),
    ],
)
async def test_only_an_explicit_pass_passes(cloud_reply, expected):
    reply = await ReaderHub(StubCloud(cloud_reply)).respond({'id': 'k'}, 'rd-1')

    assert reply == {'result': expected}


def test_reports_that_no_reader_is_connected_at_start():
    cloud = StubCloud()

    ReaderHub(cloud)

    assert cloud.reports == [[]]


async def test_reports_the_connected_readers_on_every_change(wait_until):
    cloud = StubCloud()
    hub = ReaderHub(cloud)
    rd1, rd2 = (
        ReaderConnection('rd-1', '10.10.0.2'),
        ReaderConnection('rd-2', '10.10.0.3'),
    )

    tasks = [asyncio.create_task(hub.handle(rd1))]
    await wait_until(lambda: len(cloud.reports) == 2)
    tasks.append(asyncio.create_task(hub.handle(rd2)))
    await wait_until(lambda: len(cloud.reports) == 3)
    rd1.close()
    await tasks[0]
    rd2.close()
    await tasks[1]

    assert [[reader['id'] for reader in report] for report in cloud.reports] == [
        [],
        ['rd-1'],
        ['rd-1', 'rd-2'],
        ['rd-2'],
        [],
    ]
    assert cloud.reports[1] == [
        {
            'id': 'rd-1',
            'address': '10.10.0.2',
            'since': cloud.reports[1][0]['since'],
            'key_exchange': None,
        }
    ]
