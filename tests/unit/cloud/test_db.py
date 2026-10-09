import sqlite3

import pytest

# Every reader against every example key, following cloud/seed.sql.
SEED_ACCESS = [
    ('key-alice', 'rd-1', 'pass'),
    ('key-alice', 'rd-2', 'pass'),
    ('key-alice', 'rd-3', 'fail'),
    ('key-alice', 'rd-4', 'fail'),
    ('key-bob', 'rd-1', 'pass'),
    ('key-bob', 'rd-2', 'pass'),
    ('key-bob', 'rd-3', 'pass'),
    ('key-bob', 'rd-4', 'fail'),
    ('key-carol', 'rd-1', 'pass'),
    ('key-carol', 'rd-2', 'pass'),
    ('key-carol', 'rd-3', 'fail'),
    ('key-carol', 'rd-4', 'pass'),
    ('key-alice', 'rd-5', 'pass'),
    ('key-bob', 'rd-5', 'pass'),
    ('key-carol', 'rd-5', 'fail'),
    ('key-mallory', 'rd-1', 'fail'),
    ('key-alice', 'rd-unknown', 'fail'),
]


@pytest.mark.parametrize(('key_uuid', 'reader_id', 'expected'), SEED_ACCESS)
def test_key_passes_only_where_it_shares_a_group(db, key_uuid, reader_id, expected):
    assert db.authorize(key_uuid, reader_id, 'gw-1') == expected


def test_authorize_logs_the_event(db):
    db.authorize('key-bob', 'rd-3', 'gw-1')

    [event] = db.events()
    assert event.pop('timestamp')
    assert event == {
        'key_uuid': 'key-bob',
        'reader_id': 'rd-3',
        'zone_name': 'server-room',
        'gateway_id': 'gw-1',
        'result': 'pass',
    }


def test_unknown_reader_is_logged_without_zone(db):
    db.authorize('key-bob', 'rd-unknown', 'gw-x')

    [event] = db.events()
    assert (event['zone_name'], event['gateway_id']) == (None, 'gw-x')


def test_events_are_newest_first_and_filterable(db):
    db.authorize('key-alice', 'rd-1', 'gw-1')
    db.authorize('key-bob', 'rd-1', 'gw-1')
    db.authorize('key-bob', 'rd-3', 'gw-1')

    assert [e['key_uuid'] for e in db.events()] == ['key-bob', 'key-bob', 'key-alice']
    assert [e['reader_id'] for e in db.events(key_uuid='key-bob')] == ['rd-3', 'rd-1']
    assert [e['key_uuid'] for e in db.events(reader_id='rd-1')] == [
        'key-bob',
        'key-alice',
    ]
    assert len(db.events(key_uuid='key-bob', reader_id='rd-3')) == 1
    assert len(db.events(limit=2)) == 2


def test_readers_lists_gateway_and_zone(db):
    assert db.readers() == [
        {'id': 'rd-1', 'gateway_id': 'gw-1', 'zone_name': 'front-door'},
        {'id': 'rd-2', 'gateway_id': 'gw-1', 'zone_name': 'employee-door'},
        {'id': 'rd-3', 'gateway_id': 'gw-1', 'zone_name': 'server-room'},
        {'id': 'rd-4', 'gateway_id': 'gw-1', 'zone_name': 'executive-room'},
        {'id': 'rd-5', 'gateway_id': 'gw-2', 'zone_name': 'loading-dock'},
    ]


def test_example_data_is_loaded_only_into_a_new_database(db):
    with sqlite3.connect(db.path) as conn:
        conn.execute("DELETE FROM READERS WHERE id = 'rd-4'")
    conn.close()

    db.init()

    assert len(db.readers()) == 4
