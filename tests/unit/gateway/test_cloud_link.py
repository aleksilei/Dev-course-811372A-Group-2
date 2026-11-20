import asyncio
import contextlib
import json
import socket

import pytest
from websockets.asyncio.server import serve

from gateway.cloud_link import CloudLink


@contextlib.asynccontextmanager
async def linked_to(cloud_handler, wait_until, timeout=5.0):
    """Run a fake cloud and a CloudLink connected to it."""
    async with serve(cloud_handler, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        link = CloudLink(
            f'ws://127.0.0.1:{port}', 'gw-1', None, timeout=timeout, retry_delay=0.05
        )
        task = asyncio.create_task(link.run())
        try:
            await wait_until(lambda: link.connected)
            yield link
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def answer_pass(ws):
    async for message in ws:
        request = json.loads(message)
        await ws.send(
            json.dumps({'request_id': request['request_id'], 'result': 'pass'})
        )


async def test_fails_when_not_connected():
    link = CloudLink('ws://127.0.0.1:1', 'gw-1', None)

    assert await link.request({'id': 'key-bob'}) == {'result': 'fail'}


async def test_sends_gateway_id_and_request_id(wait_until):
    seen = {}

    async def cloud(ws):
        seen['gateway_id'] = ws.request.headers['Gateway-Id']
        seen['request'] = json.loads(await ws.recv())
        await ws.send(json.dumps({**seen['request'], 'result': 'pass'}))
        await ws.wait_closed()

    async with linked_to(cloud, wait_until) as link:
        reply = await link.request({'id': 'key-bob', 'reader_id': 'rd-3'})

    assert reply['result'] == 'pass'
    assert seen['gateway_id'] == 'gw-1'
    assert seen['request'] == {
        'id': 'key-bob',
        'reader_id': 'rd-3',
        'request_id': reply['request_id'],
    }


async def test_reports_its_openssl_version_on_connect(wait_until, monkeypatch):
    monkeypatch.setenv('OPENSSL_VERSION_REPORTED', 'OpenSSL 3.5.8')
    seen = []

    async def cloud(ws):
        seen.append(ws.request.headers['OpenSSL-Version'])
        await ws.wait_closed()

    async with linked_to(cloud, wait_until):
        await wait_until(lambda: seen)

    assert seen == ['OpenSSL 3.5.8']


async def test_routes_replies_to_the_matching_request(wait_until):
    async def cloud_answering_in_reverse_order(ws):
        requests = [json.loads(await ws.recv()), json.loads(await ws.recv())]
        for request in reversed(requests):
            await ws.send(json.dumps({**request, 'result': request['id']}))
        await ws.wait_closed()

    async with linked_to(cloud_answering_in_reverse_order, wait_until) as link:
        replies = await asyncio.gather(
            link.request({'id': 'a'}), link.request({'id': 'b'})
        )

    assert [reply['result'] for reply in replies] == ['a', 'b']


async def test_fails_when_the_cloud_does_not_answer_in_time(wait_until):
    async def silent_cloud(ws):
        await ws.wait_closed()

    async with linked_to(silent_cloud, wait_until, timeout=0.1) as link:
        assert await link.request({'id': 'key-bob'}) == {'result': 'fail'}


async def test_reconnects_after_losing_the_cloud(wait_until):
    connections = []

    async def cloud_dropping_first_connection(ws):
        connections.append(ws)
        if len(connections) > 1:
            await answer_pass(ws)
        # Returning from the handler closes the connection.

    async with linked_to(cloud_dropping_first_connection, wait_until) as link:
        await wait_until(lambda: len(connections) == 2 and link.connected)

        assert (await link.request({'id': 'key-bob'}))['result'] == 'pass'


async def test_requests_fail_at_once_when_the_cloud_connection_drops(wait_until):
    async def cloud_hanging_up_on_the_first_request(ws):
        await ws.recv()

    async with linked_to(cloud_hanging_up_on_the_first_request, wait_until) as link:
        async with asyncio.timeout(1):  # well before the 5 s request timeout
            assert await link.request({'id': 'key-bob'}) == {'result': 'fail'}


async def test_keeps_retrying_until_the_cloud_is_up(wait_until, caplog):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    link = CloudLink(f'ws://127.0.0.1:{port}', 'gw-1', None, retry_delay=0.05)
    task = asyncio.create_task(link.run())
    try:
        await wait_until(lambda: caplog.text.count('cloud connection failed') >= 2)

        async with serve(answer_pass, '127.0.0.1', port):
            await wait_until(lambda: link.connected)
            assert (await link.request({'id': 'key-bob'}))['result'] == 'pass'
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_replaces_a_request_id_sent_by_the_reader(wait_until):
    # Otherwise a reader could reuse another reader's ID and get its reply.
    seen = []

    async def cloud(ws):
        async for message in ws:
            request = json.loads(message)
            seen.append(request['request_id'])
            await ws.send(json.dumps({**request, 'result': 'pass'}))

    async with linked_to(cloud, wait_until) as link:
        await link.request({'id': 'key-bob', 'request_id': 'forged'})

    assert len(seen) == 1
    assert seen[0] != 'forged'


@pytest.mark.parametrize(
    'malformed',
    [
        'not json',
        '"text"',
        '[1, 2]',
        '{"result": "pass"}',
        '{"request_id": 7, "result": "pass"}',
        # Unhashable: these used to crash run(), and with it the gateway.
        '{"request_id": ["r1"], "result": "pass"}',
        '{"request_id": {"id": "r1"}, "result": "pass"}',
    ],
)
async def test_ignores_malformed_replies(wait_until, malformed):
    async def cloud_sending_a_malformed_reply_first(ws):
        async for message in ws:
            await ws.send(malformed)
            await ws.send(json.dumps({**json.loads(message), 'result': 'pass'}))

    async with linked_to(cloud_sending_a_malformed_reply_first, wait_until) as link:
        assert (await link.request({'id': 'key-bob'}))['result'] == 'pass'
        assert link.connected


async def test_ignores_a_reply_that_comes_after_the_timeout(wait_until):
    async def cloud_answering_late(ws):
        first = json.loads(await ws.recv())
        second = json.loads(await ws.recv())  # sent once the first timed out
        await ws.send(json.dumps({**first, 'result': 'pass'}))
        await ws.send(json.dumps({**second, 'result': 'fail'}))
        await ws.wait_closed()

    async with linked_to(cloud_answering_late, wait_until, timeout=0.5) as link:
        assert await link.request({'id': 'a'}) == {'result': 'fail'}
        assert (await link.request({'id': 'b'}))['result'] == 'fail'
        assert link.connected


async def test_only_the_first_reply_to_a_request_counts(wait_until):
    async def cloud_answering_twice(ws):
        async for message in ws:
            request = json.loads(message)
            await ws.send(json.dumps({**request, 'result': 'pass'}))
            await ws.send(json.dumps({**request, 'result': 'fail'}))

    async with linked_to(cloud_answering_twice, wait_until) as link:
        assert (await link.request({'id': 'a'}))['result'] == 'pass'
        assert (await link.request({'id': 'b'}))['result'] == 'pass'


READERS = [
    {'id': 'rd-1', 'address': '10.10.0.2', 'since': 'now', 'key_exchange': 'X25519'}
]


def cloud_taking_reader_lists(received, result='ok'):
    """A cloud that records each reader list and answers it with `result`."""

    async def cloud(ws):
        async for message in ws:
            request = json.loads(message)
            if request.get('type') == 'readers':
                received.append(request['readers'])
                answer = result
            else:
                answer = 'pass'
            await ws.send(
                json.dumps({'request_id': request['request_id'], 'result': answer})
            )

    return cloud


async def test_reports_the_connected_readers(wait_until):
    received = []

    async with linked_to(cloud_taking_reader_lists(received), wait_until) as link:
        link.report_readers(READERS)
        await wait_until(lambda: received)

        link.report_readers([])
        await wait_until(lambda: len(received) == 2)

    assert received == [READERS, []]


async def test_sends_no_reader_list_until_there_is_one(wait_until):
    received = []

    async with linked_to(cloud_taking_reader_lists(received), wait_until) as link:
        assert (await link.request({'id': 'key-bob'}))['result'] == 'pass'

    assert not received


async def test_reports_the_readers_again_after_reconnecting(wait_until):
    received = []
    taking = cloud_taking_reader_lists(received)
    connections = []

    async def cloud_dropping_first_connection(ws):
        connections.append(ws)
        if len(connections) == 1:
            # Take the first list, then drop the connection.
            request = json.loads(await ws.recv())
            received.append(request['readers'])
            return
        await taking(ws)

    async with linked_to(cloud_dropping_first_connection, wait_until) as link:
        link.report_readers(READERS)
        await wait_until(lambda: len(received) == 2)

    assert received == [READERS, READERS]
    assert len(connections) == 2


async def test_an_older_cloud_refusing_reader_lists_is_only_logged(wait_until, caplog):
    received = []
    older_cloud = cloud_taking_reader_lists(received, result='fail')

    async with linked_to(older_cloud, wait_until) as link:
        link.report_readers(READERS)
        await wait_until(lambda: 'did not take the list' in caplog.text)

        assert (await link.request({'id': 'key-bob'}))['result'] == 'pass'
        assert link.connected
