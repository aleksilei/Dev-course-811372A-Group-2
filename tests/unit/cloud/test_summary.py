import pytest

from cloud.summary import summarize

HYBRID = {'key_exchange': 'X25519MLKEM768', 'post_quantum': True}
CLASSICAL = {'key_exchange': 'X25519', 'post_quantum': False}
UNKNOWN = {'key_exchange': None, 'post_quantum': None}

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
    return [{'gateway_id': gateway_id} for gateway_id in gateway_ids]


def test_all_connected_and_hybrid_is_green():
    summary = summarize(
        gateways(**{g: HYBRID for g in KNOWN}), KNOWN, READERS, events('gw-1')
    )

    assert summary['status'] == 'green'
    assert summary['readiness'] == 1.0
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
    assert summary['readiness'] == 0.75
    assert summary['classical'] == [
        {'id': 'gw-2', 'key_exchange': 'X25519', 'readers': 1, 'traffic_share': 0.5}
    ]
    assert summary['classical_traffic_share'] == 0.5
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
    assert summary['classical_traffic_share'] is None  # no traffic yet


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
    # Readiness is measured over the connected gateways only.
    assert summary['readiness'] == 1.0


def test_unknown_key_exchange_keeps_it_from_green():
    summary = summarize(
        gateways(**{'gw-1': HYBRID, 'gw-2': UNKNOWN}), ['gw-1', 'gw-2'], READERS, []
    )

    assert summary['status'] == 'amber'
    assert summary['readiness'] == 0.5
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
    assert summary['status'] == 'amber'


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
