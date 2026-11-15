from types import SimpleNamespace

from cloud.devices import STATUSES, devices

TLS13 = {'tls_version': 'TLSv1.3', 'cipher': 'TLS_AES_256_GCM_SHA384'}
READERS = [
    {'id': 'rd-1', 'gateway_id': 'gw-1', 'zone_name': 'front-door'},
    {'id': 'rd-2', 'gateway_id': 'gw-1', 'zone_name': 'employee-door'},
    {'id': 'rd-5', 'gateway_id': 'gw-2', 'zone_name': 'loading-dock'},
]


def gateway(gateway_id, group, readers=None):
    """A GatewayHub.connected() row; readers are (id, group) pairs, or None."""
    return {
        'id': gateway_id,
        **TLS13,
        'key_exchange': group,
        'post_quantum': 'MLKEM' in group.upper() if group else None,
        'readers': None
        if readers is None
        else [
            {'id': r, 'address': '10.10.0.9', 'since': 'T1', **TLS13, 'key_exchange': g}
            for r, g in readers
        ],
        'address': '172.18.0.4',
        'since': 'T0',
    }


def by_id(result):
    return {(row['type'], row['id']): row for row in result['devices']}


def test_lists_every_registered_device_even_with_nothing_connected():
    result = devices([], ['gw-1', 'gw-2'], READERS)

    assert [(row['type'], row['id']) for row in result['devices']] == [
        ('gateway', 'gw-1'),
        ('gateway', 'gw-2'),
        ('reader', 'rd-1'),
        ('reader', 'rd-2'),
        ('reader', 'rd-5'),
    ]
    rows = by_id(result)
    assert rows['gateway', 'gw-1']['status'] == 'offline'
    # Readers behind an offline gateway: unknown, never encrypted.
    assert rows['reader', 'rd-1']['state'] == 'unknown'
    assert rows['reader', 'rd-1']['status'] == 'unknown'
    assert result['counts'] == {
        'gateway': {'post-quantum': 0, 'classical': 0, 'unknown': 0, 'offline': 2},
        'reader': {'post-quantum': 0, 'classical': 0, 'unknown': 3, 'offline': 0},
    }
    assert result['statuses'] == list(STATUSES)
    assert result['panel'] is None


def test_a_gateway_has_its_link_to_the_cloud():
    result = devices([gateway('gw-1', 'X25519MLKEM768', [])], ['gw-1'], [])

    assert len(result['devices']) == 1
    row = result['devices'][0]
    assert row['state'] == 'connected'
    assert row['status'] == 'post-quantum'
    assert row['links'] == [
        {
            'name': 'gateway → cloud',
            **TLS13,
            'key_exchange': 'X25519MLKEM768',
            'post_quantum': True,
        }
    ]


def test_a_reader_is_as_strong_as_its_weakest_link():
    connected = [
        gateway('gw-1', 'X25519MLKEM768', [('rd-1', 'X25519')]),
        gateway('gw-2', 'X25519', [('rd-5', 'X25519MLKEM768')]),
    ]

    rows = by_id(devices(connected, ['gw-1', 'gw-2'], READERS))

    rd1, rd5 = rows['reader', 'rd-1'], rows['reader', 'rd-5']
    # Classical reader hop behind a hybrid gateway: classical.
    assert [link['name'] for link in rd1['links']] == [
        'reader → gateway',
        'gateway → cloud',
    ]
    assert [link['key_exchange'] for link in rd1['links']] == [
        'X25519',
        'X25519MLKEM768',
    ]
    assert rd1['status'] == 'classical'
    # A hybrid reader hop behind a classical gateway: still classical.
    assert rd5['status'] == 'classical'


def test_a_reader_with_only_post_quantum_links_is_post_quantum():
    connected = [gateway('gw-1', 'X25519MLKEM768', [('rd-1', 'X25519MLKEM768')])]

    rows = by_id(devices(connected, ['gw-1'], READERS[:1]))

    assert rows['reader', 'rd-1']['status'] == 'post-quantum'


def test_an_unreadable_key_exchange_is_unknown():
    connected = [gateway('gw-1', None, [('rd-1', None)])]

    rows = by_id(devices(connected, ['gw-1'], READERS[:1]))

    assert rows['gateway', 'gw-1']['status'] == 'unknown'
    assert rows['reader', 'rd-1']['status'] == 'unknown'


def test_a_reader_its_reporting_gateway_does_not_list_is_offline():
    connected = [gateway('gw-1', 'X25519MLKEM768', [('rd-1', 'X25519')])]

    rows = by_id(devices(connected, ['gw-1'], READERS[:2]))

    assert rows['reader', 'rd-2']['state'] == 'not connected'
    assert rows['reader', 'rd-2']['status'] == 'offline'
    assert rows['reader', 'rd-2']['links'] == []


def test_readers_behind_a_gateway_that_does_not_report_them_are_unknown():
    # e.g. a gateway from before reader lists
    connected = [gateway('gw-1', 'X25519MLKEM768', readers=None)]

    rows = by_id(devices(connected, ['gw-1'], READERS[:1]))

    assert rows['reader', 'rd-1']['state'] == 'unknown'
    assert rows['reader', 'rd-1']['status'] == 'unknown'


def test_unregistered_devices_are_unknown_but_show_their_links():
    connected = [gateway('gw-9', 'X25519MLKEM768', [('rd-99', 'X25519MLKEM768')])]

    rows = by_id(devices(connected, [], []))

    for key in [('gateway', 'gw-9'), ('reader', 'rd-99')]:
        assert rows[key]['registered'] is False
        assert rows[key]['status'] == 'unknown'
        assert rows[key]['links']


def test_a_reader_connected_through_another_gateway_is_listed_there():
    connected = [
        gateway('gw-1', 'X25519MLKEM768', []),
        gateway('gw-2', 'X25519', [('rd-1', 'X25519')]),
    ]

    rows = by_id(devices(connected, ['gw-1', 'gw-2'], READERS[:1]))

    assert rows['reader', 'rd-1']['gateway'] == 'gw-2'
    assert rows['reader', 'rd-1']['links'][1]['key_exchange'] == 'X25519'


def test_the_panel_link_is_the_requests_own_connection():
    connection = SimpleNamespace(
        version=lambda: 'TLSv1.3',
        cipher=lambda: ('TLS_AES_128_GCM_SHA256', 'TLSv1.3', 128),
        group=lambda: 'x25519',
    )

    result = devices([], [], [], connection)

    assert result['panel'] == {
        'name': 'browser → control panel',
        'tls_version': 'TLSv1.3',
        'cipher': 'TLS_AES_128_GCM_SHA256',
        'key_exchange': 'X25519',
        'post_quantum': False,
    }


def test_rows_carry_what_the_readers_list_needs():
    connected = [
        gateway('gw-1', 'X25519MLKEM768', []),
        gateway('gw-2', 'X25519', [('rd-1', 'X25519'), ('rd-99', 'X25519')]),
    ]

    rows = by_id(devices(connected, ['gw-1', 'gw-2'], READERS[:2]))

    gw1 = rows['gateway', 'gw-1']
    assert (gw1['address'], gw1['since']) == ('172.18.0.4', 'T0')
    # Registered under gw-1, connected through gw-2.
    rd1 = rows['reader', 'rd-1']
    assert (rd1['gateway'], rd1['registered_gateway'], rd1['zone_name']) == (
        'gw-2',
        'gw-1',
        'front-door',
    )
    assert (rd1['address'], rd1['since']) == ('10.10.0.9', 'T1')
    # Not connected: its database entry, but no connection details.
    rd2 = rows['reader', 'rd-2']
    assert (rd2['registered_gateway'], rd2['zone_name']) == ('gw-1', 'employee-door')
    assert (rd2['address'], rd2['since']) == (None, None)
    # Unregistered: no database entry.
    rd99 = rows['reader', 'rd-99']
    assert (rd99['registered_gateway'], rd99['zone_name']) == (None, None)
    assert rd99['gateway'] == 'gw-2'
