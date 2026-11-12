import socket
import ssl
import threading

import pytest

from lib import tls
from lib.config import ConfigError

MODES = tls.KEY_EXCHANGE_MODES

needs_mlkem = pytest.mark.skipif(
    ssl.OPENSSL_VERSION_INFO < (3, 5), reason='ML-KEM needs OpenSSL 3.5 or newer'
)


def handshake(server_context, client_context, hostname='localhost'):
    """Run one TLS handshake over localhost.

    Returns (TLS version, group the client reports, group the server reports),
    the groups as tls.negotiated_group() reports them. Raises the client's
    ssl.SSLError if the handshake fails.
    """
    server_groups = []
    with socket.create_server(('127.0.0.1', 0)) as listener:
        listener.settimeout(5)

        def accept():
            conn, _ = listener.accept()
            conn.settimeout(5)
            try:
                with server_context.wrap_socket(conn, server_side=True) as tls_conn:
                    server_groups.append(tls.negotiated_group(tls_conn))
                    tls_conn.recv(1)
            except OSError:  # includes ssl.SSLError
                pass

        thread = threading.Thread(target=accept)
        thread.start()
        try:
            with (
                socket.create_connection(listener.getsockname(), timeout=5) as sock,
                client_context.wrap_socket(sock, server_hostname=hostname) as conn,
            ):
                version, client_group = conn.version(), tls.negotiated_group(conn)
        finally:
            thread.join()
    return version, client_group, server_groups[0] if server_groups else None


def negotiate(certs, client_groups, server_groups):
    """The group a client and a server with these group lists agree on, as both
    ends report it, or None if they can't connect."""
    try:
        _, client_group, server_group = handshake(
            tls.server_context(certs.cert, certs.key, server_groups),
            tls.client_context(certs.ca, client_groups),
        )
    except ssl.SSLError:
        return None
    assert client_group == server_group
    return client_group


@pytest.fixture(name='server')
def server_fixture(certs):
    return tls.server_context(certs.cert, certs.key, tls.READER_GATEWAY)


@pytest.fixture(name='client')
def client_fixture(certs):
    return tls.client_context(certs.ca, tls.READER_GATEWAY)


@pytest.fixture(name='no_key_exchange_env')
def no_key_exchange_env_fixture(monkeypatch):
    monkeypatch.delenv('KEY_EXCHANGE', raising=False)
    monkeypatch.delenv('OPENSSL_CONF', raising=False)
    return monkeypatch


def test_the_reader_and_admin_hops_are_pinned_to_x25519():
    assert tls.READER_GATEWAY == tls.ADMIN_CLOUD == 'X25519'


@pytest.mark.usefixtures('no_key_exchange_env')
def test_gateway_cloud_hop_is_hybrid_by_default():
    assert tls.gateway_cloud() == '*X25519MLKEM768:*X25519'


@pytest.mark.parametrize('mode', list(MODES))
def test_gateway_cloud_hop_follows_key_exchange(no_key_exchange_env, mode):
    no_key_exchange_env.setenv('KEY_EXCHANGE', mode)

    assert tls.gateway_cloud() == MODES[mode]


def test_unknown_key_exchange_is_an_error(no_key_exchange_env):
    no_key_exchange_env.setenv('KEY_EXCHANGE', 'hybird')

    with pytest.raises(ConfigError, match='KEY_EXCHANGE'):
        tls.gateway_cloud()


def test_leftover_openssl_conf_is_an_error(no_key_exchange_env):
    # A Python 3.13 override like this one points to a file that no longer
    # exists, which OpenSSL would silently ignore.
    no_key_exchange_env.setenv('OPENSSL_CONF', '/opt/lib/openssl/hybrid-only.cnf')

    with pytest.raises(ConfigError, match='OPENSSL_CONF'):
        tls.gateway_cloud()


# `classical` offers what gateways and clouds from before ML-KEM offer (X25519
# pinned in the code), and `hybrid` what the Python 3.13 version offers with
# hybrid.cnf, so the matrix also covers mixed fleets during upgrades.
@needs_mlkem
@pytest.mark.parametrize(
    ('gateway', 'cloud', 'group'),
    [
        ('hybrid', 'hybrid', 'X25519MLKEM768'),
        ('hybrid', 'classical', 'X25519'),
        ('classical', 'hybrid', 'X25519'),
        ('hybrid', 'hybrid-only', 'X25519MLKEM768'),
        ('hybrid-only', 'hybrid', 'X25519MLKEM768'),
        ('hybrid-only', 'hybrid-only', 'X25519MLKEM768'),
        ('classical', 'hybrid-only', None),
        ('hybrid-only', 'classical', None),
    ],
)
def test_gateway_cloud_key_exchange(certs, gateway, cloud, group):
    assert negotiate(certs, MODES[gateway], MODES[cloud]) == group


@needs_mlkem
def test_pinned_hops_stay_classical(certs):
    # A hybrid client (e.g. the e2e probe in a gateway) gets X25519 from the
    # reader port and the control panel, and a hybrid-only one gets nothing.
    assert negotiate(certs, MODES['hybrid'], tls.READER_GATEWAY) == 'X25519'
    assert negotiate(certs, MODES['hybrid-only'], tls.READER_GATEWAY) is None


def test_classical_group_is_reported_as_x25519(certs):
    # OpenSSL itself reports x25519 in lower case.
    assert negotiate(certs, 'X25519', 'X25519') == 'X25519'


def test_unknown_group_names_are_reported_as_openssl_spells_them():
    class Connection:  # stands in for an SSLObject
        def group(self):
            return 'SecP256r1MLKEM768'

    assert tls.negotiated_group(Connection()) == 'SecP256r1MLKEM768'


def test_group_is_unknown_without_a_handshake(client):
    before_handshake = client.wrap_bio(
        ssl.MemoryBIO(), ssl.MemoryBIO(), server_hostname='localhost'
    )

    assert tls.negotiated_group(before_handshake) is None
    assert tls.negotiated_group(None) is None


def test_handshake_uses_tls_1_3(server, client):
    assert handshake(server, client)[0] == 'TLSv1.3'


def test_client_verifies_the_server_hostname(server, client):
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(server, client, hostname='not-in-the-certificate')


def test_server_accepts_only_its_group(certs, server):
    other_client = ssl.create_default_context(cafile=certs.ca)
    assert handshake(server, other_client)[0] == 'TLSv1.3'

    other_client.set_groups('P-256')
    with pytest.raises(ssl.SSLError):
        handshake(server, other_client)


def test_client_offers_only_its_group(certs, client):
    # A P-256-only server would work with a default client (via a retry), so
    # failing here proves the client offers nothing but X25519 - no ML-KEM.
    other_server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    other_server.load_cert_chain(certs.cert, certs.key)
    other_server.set_groups('P-256')
    assert handshake(other_server, ssl.create_default_context(cafile=certs.ca))

    with pytest.raises(ssl.SSLError):
        handshake(other_server, client)


@pytest.mark.parametrize(
    ('group', 'post_quantum'),
    [
        ('X25519MLKEM768', True),
        ('SecP384r1MLKEM1024', True),
        ('X25519', False),
        ('x25519', False),  # the spelling OpenSSL itself uses
        (None, None),
    ],
)
def test_is_post_quantum(group, post_quantum):
    assert tls.is_post_quantum(group) is post_quantum
