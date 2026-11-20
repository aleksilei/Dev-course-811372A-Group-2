"""End-to-end: the docker-compose deployment, from the built images, seen the
way the doors and an admin see it. Run with `make e2e` (see README.md).

The tests run in this order and share one stack; the last two take the cloud
down and bring it back.
"""

import pytest

from lib import openssl
from tests.e2e.stack import wait_for

# Who may open which door with the example data in cloud/seed.sql.
SEED_ACCESS = {
    'key-alice': {'rd-1', 'rd-2', 'rd-5'},
    'key-bob': {'rd-1', 'rd-2', 'rd-3', 'rd-5'},
    'key-carol': {'rd-1', 'rd-2', 'rd-4'},
    'key-mallory': set(),
}
# Reader ID -> (compose service, zone, gateway), as in docker-compose.yml.
READERS = {
    'rd-1': ('reader-1', 'front-door', 'gw-1'),
    'rd-2': ('reader-2', 'employee-door', 'gw-1'),
    'rd-3': ('reader-3', 'server-room', 'gw-1'),
    'rd-4': ('reader-4', 'executive-room', 'gw-1'),
    'rd-5': ('reader-5', 'loading-dock', 'gw-2'),
}
HYBRID_ONLY = ('docker-compose.yml', 'tests/e2e/compose.hybrid-only.yml')
# make migrate: the cloud and gateway-1 on the -openssl<version> images.
MIGRATED = ('docker-compose.yml', 'docker-compose.migrated.yml')


def seed_outcome(key: str, reader_id: str) -> str:
    return 'PASS' if reader_id in SEED_ACCESS[key] else 'FAIL'


def scans_once_a_key_that_passes_is_scanned(stack, reader_id, since):
    """The reader's scans since `since`, or None until one of them was of a
    key that the example data lets through that door."""
    scans = stack.scans(READERS[reader_id][0], since)
    if any(seed_outcome(key, reader_id) == 'PASS' for _, key in scans):
        return scans
    return None


def test_gateways_connect_with_the_key_exchange_they_support(stack):
    gateways = stack.api('gateways')

    # gateway-2 stands in for a gateway without ML-KEM (KEY_EXCHANGE=classical).
    assert {g['id']: (g['key_exchange'], g['post_quantum']) for g in gateways} == {
        'gw-1': ('X25519MLKEM768', True),
        'gw-2': ('X25519', False),
    }


def test_every_door_decides_by_the_example_data(stack):
    since = {
        reader_id: stack.mark(service) for reader_id, (service, _, _) in READERS.items()
    }
    scans = {}

    def three_scans_at_every_door():
        for reader_id, (service, _, _) in READERS.items():
            scans[reader_id] = stack.scans(service, since[reader_id])
        return all(len(reader_scans) >= 3 for reader_scans in scans.values())

    wait_for(three_scans_at_every_door, 'three scans at every reader')

    wrong = [
        (reader_id, key, outcome)
        for reader_id, reader_scans in scans.items()
        for outcome, key in reader_scans
        if outcome != seed_outcome(key, reader_id)
    ]
    assert wrong == []


def test_the_cloud_logs_every_scan_with_its_zone_and_gateway(stack):
    events = stack.api('events')

    assert {event['reader_id'] for event in events} == set(READERS)
    wrong = [
        event
        for event in events
        if (event['zone_name'], event['gateway_id'], event['result'].upper())
        != (
            *READERS[event['reader_id']][1:],
            seed_outcome(event['key_uuid'], event['reader_id']),
        )
    ]
    assert wrong == []


def test_readers_are_listed_with_their_gateway_and_zone(stack):
    assert stack.api('readers') == [
        {'id': reader_id, 'gateway_id': gateway, 'zone_name': zone}
        for reader_id, (_, zone, gateway) in READERS.items()
    ]


def test_each_gateway_reports_the_readers_connected_to_it(stack):
    # Readers connect on their first scan, within SCAN_INTERVAL of starting.
    expected = {}
    for reader_id, (_, _, gateway) in READERS.items():
        expected.setdefault(gateway, []).append(reader_id)

    def reported():
        gateways = stack.api('gateways')
        listed = {
            gateway['id']: [reader['id'] for reader in gateway['readers'] or []]
            for gateway in gateways
        }
        return gateways if listed == expected else None

    gateways = wait_for(reported, 'every reader listed under its gateway')
    readers = [reader for gateway in gateways for reader in gateway['readers']]
    # The reader -> gateway hop is classical, per the spec.
    assert {(r['key_exchange'], r['post_quantum']) for r in readers} == {
        ('X25519', False)
    }


def test_every_device_reports_tls_1_3_and_its_key_exchange(stack):
    # gateway-1 has ML-KEM, gateway-2 doesn't; every reader hop is classical.
    expected_groups = {
        ('gateway', 'gw-1'): ['X25519MLKEM768'],
        ('gateway', 'gw-2'): ['X25519'],
    }
    for reader_id, (_, _, gateway) in READERS.items():
        expected_groups['reader', reader_id] = [
            'X25519',
            'X25519MLKEM768' if gateway == 'gw-1' else 'X25519',
        ]

    def all_connected():
        result = stack.api('devices')
        rows = result['devices']
        connected = all(row['state'] == 'connected' for row in rows)
        return result if connected and len(rows) == len(expected_groups) else None

    result = wait_for(all_connected, 'every device connected')

    rows = {(row['type'], row['id']): row for row in result['devices']}
    assert {
        key: [link['key_exchange'] for link in row['links']]
        for key, row in rows.items()
    } == expected_groups
    links = [link for row in rows.values() for link in row['links']]
    assert {link['tls_version'] for link in links} == {'TLSv1.3'}
    assert all(link['cipher'].startswith('TLS_') for link in links)
    assert rows['gateway', 'gw-1']['status'] == 'post-quantum'
    assert result['counts']['reader']['classical'] == len(READERS)
    assert result['panel']['tls_version'] == 'TLSv1.3'


def test_every_device_reports_the_images_openssl_and_its_vulnerability(stack):
    # The default stack starts on the base image's OpenSSL everywhere.
    result = stack.api('devices')
    reports = [*result['devices'], result['cloud']]
    versions = {report['openssl'] for report in reports}
    assert len(versions) == 1
    [version] = versions
    assert version.startswith('OpenSSL 3.')
    vulnerable = openssl.is_vulnerable(version)
    assert {report['openssl_vulnerable'] for report in reports} == {vulnerable}
    assert {report['openssl_checked'] for report in reports} == {True}

    # gw-1 negotiates hybrid: with a vulnerable ML-KEM it counts as weakened.
    summary = stack.api('summary')
    assert [g['id'] for g in summary['weakened']] == (['gw-1'] if vulnerable else [])


def test_migrating_the_cloud_and_the_gateways_ends_the_weakening(stack):
    base = stack.api('devices')['cloud']['openssl']
    patched = f'OpenSSL {stack.openssl["OPENSSL_VERSION"]} '
    gateways = ['gateway-1', 'gateway-2']
    stack.up('cloud', *gateways, files=MIGRATED)
    try:

        def migrated():
            result = stack.api('devices')
            rows = {(row['type'], row['id']): row for row in result['devices']}
            gateway_rows = [rows['gateway', 'gw-1'], rows['gateway', 'gw-2']]
            done = all(
                row['state'] == 'connected'
                and (row['openssl'] or '').startswith(patched)
                for row in gateway_rows
            )
            return (result, gateway_rows, rows) if done else None

        result, gateway_rows, rows = wait_for(
            migrated, 'both gateways back on the patched OpenSSL'
        )
        assert result['cloud']['openssl'].startswith(patched)
        assert result['cloud']['openssl_vulnerable'] is False
        assert {row['openssl_vulnerable'] for row in gateway_rows} == {False}
        # The readers' hop is classical: they keep the base image's OpenSSL.
        assert {
            row['openssl'] for (kind, _), row in rows.items() if kind == 'reader'
        } <= {
            base,
            None,  # not reconnected yet
        }

        # gw-1 is hybrid again; gw-2, still classical, keeps the status amber.
        summary = stack.api('summary')
        assert summary['weakened'] == []
        assert (summary['gateways']['hybrid'], summary['gateways']['weakened']) == (
            1,
            0,
        )
        assert summary['status'] == 'amber'
    finally:
        stack.up('cloud', *gateways)
        stack.wait_until_connected()


@pytest.mark.parametrize(
    ('client', 'server', 'group'),
    [
        ('gateway-1', '10.10.0.10:8765', 'X25519'),  # reader -> gateway
        ('gateway-1', 'cloud:8444', 'X25519'),  # admin -> control panel
        ('gateway-1', 'cloud:8443', 'X25519MLKEM768'),  # gateway -> cloud
        ('gateway-2', 'cloud:8443', 'X25519'),  # gateway without ML-KEM -> cloud
    ],
)
def test_each_hop_negotiates_the_key_exchange_of_the_spec(stack, client, server, group):
    # From gateway-1 the probe offers X25519MLKEM768 first, so X25519 means the
    # server refused the hybrid: the spec's classical hops stay classical.
    assert stack.probe(client, server) == group


def test_a_key_the_admin_adds_to_a_group_opens_its_doors(stack):
    # visitors may only open the front door (rd-1).
    grant = {'key': 'key-mallory', 'group': 'visitors', 'member': True}
    since = stack.mark('reader-1')
    stack.api('key-groups', grant)
    try:
        wait_for(
            lambda: ('PASS', 'key-mallory') in stack.scans('reader-1', since),
            'the front door to let key-mallory in',
        )
    finally:
        since = stack.mark('reader-1')
        stack.api('key-groups', {**grant, 'member': False})

    wait_for(
        lambda: ('FAIL', 'key-mallory') in stack.scans('reader-1', since),
        'the front door to turn key-mallory away again',
    )


def test_doors_stay_closed_while_the_cloud_is_down(stack):
    stack.compose('stop', '--timeout', '1', 'cloud')
    since = stack.mark('reader-1')
    try:
        scans = wait_for(
            lambda: scans_once_a_key_that_passes_is_scanned(stack, 'rd-1', since),
            'the front door to scan a key it would let in',
        )
        assert {outcome for outcome, _ in scans} == {'FAIL'}
    finally:
        stack.compose('start', 'cloud')
        stack.wait_until_connected()

    since = stack.mark('reader-1')
    wait_for(
        lambda: 'PASS' in {outcome for outcome, _ in stack.scans('reader-1', since)},
        'the front door to let keys in again',
    )


def test_a_hybrid_only_cloud_refuses_the_gateway_without_ml_kem(stack):
    stack.up('cloud', files=HYBRID_ONLY)
    try:
        wait_for(lambda: 'gw-1' in stack.gateways(), 'gateway-1 to reconnect')
        # The cloud is up, so gateway-2's attempts from now on are refusals (the
        # cloud aborts the handshake, which gateway-2 sees as a reset).
        since = stack.mark('gateway-2')
        wait_for(
            lambda: (
                sum(
                    'cloud connection failed' in line
                    for line in stack.logs('gateway-2')[since:]
                )
                >= 2
            ),
            'gateway-2 to be refused twice',
        )
        assert stack.gateways() == {'gw-1': 'X25519MLKEM768'}

        # reader-5 is behind gateway-2: its door fails closed.
        since = stack.mark('reader-5')
        scans = wait_for(
            lambda: scans_once_a_key_that_passes_is_scanned(stack, 'rd-5', since),
            'the loading dock to scan a key it would let in',
        )
        assert {outcome for outcome, _ in scans} == {'FAIL'}
    finally:
        stack.up('cloud')
        stack.wait_until_connected()
