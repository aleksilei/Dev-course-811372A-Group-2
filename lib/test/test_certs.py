import ssl

from lib.certs import COMPOSE_SERVERS, generate


def test_generates_ca_and_one_key_pair_per_server(tmp_path):
    generate(tmp_path, {'one': 'DNS:one', 'two': 'DNS:two'})

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        'ca.key',
        'ca.pem',
        'one.key',
        'one.pem',
        'two.key',
        'two.pem',
    ]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / 'one.pem', tmp_path / 'one.key')


def test_compose_certificates_match_the_compose_addresses():
    assert 'IP:10.10.0.10' in COMPOSE_SERVERS['gateway']
    assert 'IP:10.10.0.11' in COMPOSE_SERVERS['gateway-2']
    assert 'DNS:cloud' in COMPOSE_SERVERS['cloud']
