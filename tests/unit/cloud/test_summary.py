import pytest

from cloud.summary import summarize
from lib import openssl

HYBRID = {'key_exchange': 'X25519MLKEM768', 'post_quantum': True}
CLASSICAL = {'key_exchange': 'X25519', 'post_quantum': False}
UNKNOWN = {'key_exchange': None, 'post_quantum': None}
# Hybrid key exchange, but on an OpenSSL whose ML-KEM is vulnerable (SCRUM-51).
AFFECTED_VERSION = 'OpenSSL 3.5.7 9 Jun 2026'
PATCHED_VERSION = 'OpenSSL 3.5.8'
WEAKENED = {**HYBRID, **openssl.details(AFFECTED_VERSION)}
PATCHED = {**HYBRID, **openssl.details(PATCHED_VERSION)}
PATCHED_LINK = {'gateway_openssl': PATCHED_VERSION, 'cloud_openssl': PATCHED_VERSION}

READERS = [
    {'id': 'rd-1', 'gateway_id': 'gw-1', 'zone_name': 'front-door'},
    {'id': 'rd-2', 'gateway_id': 'gw-1', 'zone_name': 'employee-door'},
    {'id': 'rd-3', 'gateway_id': 'gw-2', 'zone_name': 'loading-dock'},
    {'id': 'rd-4', 'gateway_id': 'gw-3', 'zone_name': 'lab'},
    {'id': 'rd-5', 'gateway_id': 'gw-4', 'zone_name': 'storage'},
]
KNOWN = ['gw-1', 'gw-2', 'gw-3', 'gw-4']


def gateways(**kinds):
    return [{'id': gateway_id, **kind} for gateway_id, kind in kinds.items()]


def events(*gateway_ids):
    return [
        {
            **PATCHED_LINK,
            'gateway_id': gateway_id,
            'key_exchange': 'X25519' if gateway_id == 'gw-2' else 'X25519MLKEM768',
        }
        for gateway_id in gateway_ids
    ]


def test_all_connected_and_hybrid_is_green():
    summary = summarize(
        gateways(**{g: HYBRID for g in KNOWN}), KNOWN, READERS, events('gw-1')
    )

    assert summary['status'] == 'green'
    assert summary['readiness'] == 1.0
    assert summary['gateway_coverage'] == 1.0
    assert summary['risks'] == []
    assert summary['classical'] == []


def test_one_classical_gateway_is_amber_with_its_exposure():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': CLASSICAL, 'gw-3': HYBRID, 'gw-4': HYBRID}),
        KNOWN,
        READERS,
        events('gw-1', 'gw-2', 'gw-2', 'gw-3'),
    )

    assert summary['status'] == 'amber'
    assert summary['readiness'] == 0.5
    assert summary['gateway_coverage'] == 0.75
    assert summary['classical'] == [
        {'id': 'gw-2', 'key_exchange': 'X25519', 'readers': 1, 'traffic_share': 0.5}
    ]
    assert summary['classical_traffic_share'] == 0.5
    assert summary['non_pqc_traffic_share'] == 0.5
    assert summary['hybrid_only_disconnects'] == {'gateways': 1, 'readers': 1}
    assert [risk['severity'] for risk in summary['risks']] == ['medium', 'medium']
    assert 'gw-2' in summary['risks'][0]['gateways']


def test_more_than_half_classical_is_red():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': CLASSICAL, 'gw-3': CLASSICAL}),
        ['gw-1', 'gw-2', 'gw-3'],
        READERS,
        [],
    )

    assert summary['status'] == 'red'
    assert summary['risks'][0]['severity'] == 'high'
    assert summary['readiness'] is None  # no traffic yet
    assert summary['gateway_coverage'] == 0.333
    assert summary['classical_traffic_share'] is None


def test_exactly_half_classical_is_amber():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': CLASSICAL}), ['gw-1', 'gw-2'], READERS, []
    )

    assert summary['status'] == 'amber'


def test_an_offline_gateway_is_red_and_the_first_risk():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': HYBRID, 'gw-3': HYBRID}),
        KNOWN,
        READERS,
        [],
    )

    assert summary['status'] == 'red'
    assert summary['gateways']['offline'] == 1
    assert summary['offline'][0]['id'] == 'gw-4'
    assert summary['risks'][0]['title'] == '1 site gateway offline'
    assert summary['risks'][0]['detail'].startswith('1 door ')
    # Coverage uses connected gateways; traffic readiness needs traffic.
    assert summary['gateway_coverage'] == 1.0
    assert summary['readiness'] is None


def test_unknown_key_exchange_keeps_it_from_green():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': UNKNOWN}), ['gw-1', 'gw-2'], READERS, []
    )

    assert summary['status'] == 'amber'
    assert summary['readiness'] is None
    assert summary['gateway_coverage'] == 0.5
    assert summary['risks'][-1]['severity'] == 'low'


def test_a_connected_gateway_missing_from_the_database_still_counts():
    summary = summarize(gateways(**{'gw-x': CLASSICAL}), [], [], [])

    assert summary['gateways']['known'] == 1
    assert summary['classical'][0] == {
        'id': 'gw-x',
        'key_exchange': 'X25519',
        'readers': 0,
        'traffic_share': None,
    }


def test_nothing_connected_or_known_has_no_readiness():
    summary = summarize([], [], [], [])

    assert summary['readiness'] is None
    assert summary['gateway_coverage'] is None
    assert summary['status'] == 'amber'


def test_traffic_readiness_weights_gateways_by_access_volume():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': CLASSICAL}),
        ['gw-1', 'gw-2'],
        READERS,
        [],
        traffic_counts=[
            {'gateway_id': 'gw-1', **HYBRID, **PATCHED_LINK, 'count': 9},
            {'gateway_id': 'gw-2', 'key_exchange': 'X25519', 'count': 1},
        ],
    )

    assert summary['readiness'] == 0.9
    assert summary['gateway_coverage'] == 0.5
    assert summary['non_pqc_traffic_share'] == 0.1
    assert summary['classical'][0]['traffic_share'] == 0.1
    assert summary['recent_events'] == 10


def test_unknown_and_offline_traffic_counts_as_non_pqc():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': UNKNOWN}),
        ['gw-1', 'gw-2', 'gw-3'],
        READERS,
        [],
        traffic_counts=[
            {'gateway_id': 'gw-1', **HYBRID, **PATCHED_LINK, 'count': 2},
            {'gateway_id': 'gw-2', 'key_exchange': None, 'count': 2},
            {'gateway_id': 'gw-3', 'key_exchange': None, 'count': 2},
        ],
    )

    assert summary['readiness'] == 0.333
    assert summary['non_pqc_traffic_share'] == 0.667
    assert summary['unknown'][0]['traffic_share'] == 0.333
    assert summary['offline'][0]['traffic_share'] == 0.333


def test_readiness_uses_event_encryption_across_upgrades_and_disconnects():
    traffic = [
        {'gateway_id': 'gw-1', 'key_exchange': 'X25519', 'count': 3},
        {'gateway_id': 'gw-1', **HYBRID, **PATCHED_LINK, 'count': 4},
        {'gateway_id': 'gw-2', **HYBRID, **PATCHED_LINK, 'count': 2},
        {
            'gateway_id': 'gw-1',
            **HYBRID,
            **PATCHED_LINK,
            'gateway_openssl': AFFECTED_VERSION,
            'count': 1,
        },
        {
            'gateway_id': 'gw-1',
            **HYBRID,
            **PATCHED_LINK,
            'cloud_openssl': AFFECTED_VERSION,
            'count': 1,
        },
        {'gateway_id': 'gw-1', **HYBRID, 'cloud_openssl': PATCHED_VERSION, 'count': 1},
    ]
    for connected in (
        gateways(**{'gw-1': PATCHED}),
        [],
        gateways(**{'gw-1': CLASSICAL}),
    ):
        summary = summarize(connected, ['gw-1', 'gw-2'], [], [], traffic_counts=traffic)
        assert summary['readiness'] == 0.5
        assert summary['non_pqc_traffic_share'] == 0.5
        assert summary['classical_traffic_share'] == 0.25


@pytest.mark.parametrize('record', [{}, HYBRID])
def test_legacy_events_remain_unknown_even_when_gateway_is_hybrid(record):
    summary = summarize(
        gateways(**{'gw-1': PATCHED}), ['gw-1'], [], [{'gateway_id': 'gw-1', **record}]
    )
    assert summary['readiness'] == 0
    assert summary['non_pqc_traffic_share'] == 1


@pytest.mark.parametrize(
    ('kinds', 'expected'),
    [({'gw-1': HYBRID}, 'green'), ({'gw-1': CLASSICAL}, 'red')],
)
def test_a_single_gateway(kinds, expected):
    assert summarize(gateways(**kinds), ['gw-1'], READERS, [])['status'] == expected


def test_gateways_are_listed_in_natural_order():
    summary = summarize(
        gateways(**{'gw-s10': CLASSICAL, 'gw-s9': CLASSICAL, 'gw-s2': HYBRID}),
        ['gw-s10', 'gw-s9', 'gw-s2', 'gw-s11'],
        [],
        [],
    )

    assert [g['id'] for g in summary['classical']] == ['gw-s9', 'gw-s10']


def test_a_hybrid_gateway_on_vulnerable_openssl_counts_like_a_classical_one():
    summary = summarize(
        gateways(**{'gw-1': WEAKENED, 'gw-2': PATCHED, 'gw-3': HYBRID, 'gw-4': HYBRID}),
        KNOWN,
        READERS,
        [],
    )

    assert summary['status'] == 'amber'
    assert summary['gateways']['hybrid'] == 3
    assert summary['gateways']['weakened'] == 1
    assert summary['gateway_coverage'] == 0.75
    assert summary['weakened'] == [
        {
            'id': 'gw-1',
            'key_exchange': 'X25519MLKEM768',
            'readers': 2,
            'traffic_share': None,
            'openssl': AFFECTED_VERSION,
        }
    ]
    [risk] = summary['risks']
    assert risk['severity'] == 'medium'
    assert risk['title'] == '1 of 4 gateways runs a vulnerable OpenSSL'
    assert risk['gateways'] == ['gw-1']
    # Turning off classical fallback would not cut it off: it is hybrid.
    assert summary['hybrid_only_disconnects'] == {'gateways': 0, 'readers': 0}


def test_more_than_half_classical_or_weakened_is_red():
    summary = summarize(
        gateways(**{'gw-1': WEAKENED, 'gw-2': CLASSICAL}), ['gw-1', 'gw-2'], READERS, []
    )

    assert summary['status'] == 'red'
    assert summary['gateway_coverage'] == 0.0
    titles = [risk['title'] for risk in summary['risks']]
    assert titles[:2] == [
        '1 of 2 gateways uses classical encryption',
        '1 of 2 gateways runs a vulnerable OpenSSL',
    ]
    assert summary['risks'][1]['severity'] == 'high'


def test_only_hybrid_gateways_can_be_weakened():
    # A classical gateway's ML-KEM is never used.
    summary = summarize(
        gateways(**{'gw-1': PATCHED, 'gw-2': {**CLASSICAL, **openssl.details(None)}}),
        ['gw-1', 'gw-2'],
        READERS,
        [],
    )

    assert summary['gateways']['weakened'] == 0
    assert summary['gateways']['hybrid'] == 1
    assert summary['status'] == 'amber'


def test_a_hybrid_gateway_that_does_not_report_its_openssl_is_weakened():
    # e.g. a gateway from before SCRUM-51, never restarted onto a patch.
    summary = summarize(
        gateways(**{'gw-1': {**HYBRID, **openssl.details(None)}, 'gw-2': PATCHED}),
        ['gw-1', 'gw-2'],
        READERS,
        [],
    )

    assert [g['id'] for g in summary['weakened']] == ['gw-1']
    assert summary['weakened'][0]['openssl'] is None


def test_a_vulnerable_cloud_weakens_every_hybrid_gateway():
    summary = summarize(
        gateways(**{'gw-1': PATCHED, 'gw-2': CLASSICAL}),
        ['gw-1', 'gw-2'],
        READERS,
        [],
        cloud_openssl=AFFECTED_VERSION,
    )

    assert [g['id'] for g in summary['weakened']] == ['gw-1']
    assert summary['cloud']['openssl_vulnerable'] is True
    assert summary['status'] == 'red'
    risk = next(r for r in summary['risks'] if r['gateways'] == ['gw-1'])
    assert risk['title'] == 'The cloud runs a vulnerable OpenSSL'
    assert '1 of 2 gateways' in risk['detail']
    assert 'upgraded to 3.5.8 or newer' in risk['detail']


def test_a_patched_cloud_leaves_patched_gateways_protected():
    summary = summarize(
        gateways(**{'gw-1': PATCHED, 'gw-2': PATCHED}),
        ['gw-1', 'gw-2'],
        READERS,
        [],
        cloud_openssl='OpenSSL 3.5.9 29 Sep 2026',
    )

    assert summary['status'] == 'green'
    assert summary['gateways']['weakened'] == 0
    assert summary['cloud']['openssl_vulnerable'] is False
