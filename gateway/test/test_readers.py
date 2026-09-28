import pytest

from gateway.readers import ReaderHub


class StubCloud:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    async def request(self, request):
        self.requests.append(request)
        return self.reply


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
