import pytest

from cloud.gateways import GatewayHub


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
