import os
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from lib import tls
from lib.config import ConfigError

OPENSSL_CONFIGS = Path(__file__).parents[1] / 'openssl'
PEER = Path(__file__).with_name('tls_peer.py')

# How each version of a gateway or cloud sets up the gateway -> cloud hop:
# (the OpenSSL config its image loads, the group it pins in lib.tls).
VERSIONS = {
    'v1': (None, 'X25519'),  # before ML-KEM: X25519 pinned in the code
    'hybrid': ('hybrid.cnf', tls.GATEWAY_CLOUD),
    'hybrid-only': ('hybrid-only.cnf', tls.GATEWAY_CLOUD),
    'classical': ('classical.cnf', tls.GATEWAY_CLOUD),
}

needs_mlkem = pytest.mark.skipif(
    ssl.OPENSSL_VERSION_INFO < (3, 5), reason='ML-KEM needs OpenSSL 3.5 or newer'
)


def handshake(server_context, client_context, hostname='localhost'):
    """Run one TLS handshake over localhost and return the negotiated version."""
    with socket.create_server(('127.0.0.1', 0)) as listener:
        listener.settimeout(5)

        def accept():
            conn, _ = listener.accept()
            conn.settimeout(5)
            try:
                with server_context.wrap_socket(conn, server_side=True) as tls_conn:
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
                return conn.version()
        finally:
            thread.join()


def peer(role, version, *args):
    """Popen/run arguments for tls_peer.py set up as version (config, group)."""
    config, group = version
    env = {name: value for name, value in os.environ.items() if name != 'OPENSSL_CONF'}
    if config is not None:
        env['OPENSSL_CONF'] = str(OPENSSL_CONFIGS / config)
    return {'args': [sys.executable, PEER, role, *args, group or '-'], 'env': env}


def negotiate(certs, client, server):
    """Handshake between two processes set up as (config, group) versions.

    Returns the key-exchange group both ends report through
    tls.negotiated_group(), or None if they couldn't connect.
    """
    with subprocess.Popen(
        **peer('server', server, certs.cert, certs.key),
        stdout=subprocess.PIPE,
        text=True,
    ) as server_process:
        port = server_process.stdout.readline().strip()
        client_process = subprocess.run(
            **peer('client', client, certs.ca, port),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        server_group = server_process.stdout.read().strip() or None
    client_group = client_process.stdout.strip() or None
    assert client_group == server_group
    return server_group


@pytest.fixture(name='server')
def server_fixture(certs):
    return tls.server_context(certs.cert, certs.key, tls.READER_GATEWAY)


@pytest.fixture(name='client')
def client_fixture(certs):
    return tls.client_context(certs.ca, tls.READER_GATEWAY)


def test_only_the_gateway_cloud_hop_is_left_to_the_openssl_config():
    assert tls.READER_GATEWAY == tls.ADMIN_CLOUD == 'X25519'
    assert tls.GATEWAY_CLOUD is None


@needs_mlkem
@pytest.mark.parametrize(
    ('gateway', 'cloud', 'group'),
    [
        ('hybrid', 'hybrid', 'X25519MLKEM768'),
        ('hybrid', 'v1', 'X25519'),
        ('v1', 'hybrid', 'X25519'),
        ('classical', 'hybrid', 'X25519'),
        ('hybrid', 'hybrid-only', 'X25519MLKEM768'),
        ('hybrid-only', 'hybrid', 'X25519MLKEM768'),
        ('hybrid-only', 'hybrid-only', 'X25519MLKEM768'),
        ('v1', 'hybrid-only', None),
        ('classical', 'hybrid-only', None),
        ('hybrid-only', 'v1', None),
    ],
)
def test_gateway_cloud_key_exchange(certs, gateway, cloud, group):
    assert negotiate(certs, VERSIONS[gateway], VERSIONS[cloud]) == group


@needs_mlkem
def test_pinned_hops_stay_classical_under_the_hybrid_config(certs):
    # The reader port and the control panel run in processes that load
    # hybrid.cnf for the gateway -> cloud hop.
    pinned_server = ('hybrid.cnf', tls.READER_GATEWAY)

    assert negotiate(certs, VERSIONS['hybrid'], pinned_server) == 'X25519'
    assert negotiate(certs, VERSIONS['hybrid-only'], pinned_server) is None


def test_missing_openssl_config_is_an_error(certs, monkeypatch):
    # OpenSSL itself would silently fall back to its default groups.
    monkeypatch.setenv('OPENSSL_CONF', str(OPENSSL_CONFIGS / 'nope.cnf'))

    with pytest.raises(ConfigError):
        tls.client_context(certs.ca, tls.GATEWAY_CLOUD)


def test_handshake_uses_tls_1_3(server, client):
    assert handshake(server, client) == 'TLSv1.3'


def test_client_verifies_the_server_hostname(server, client):
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(server, client, hostname='not-in-the-certificate')


def test_server_accepts_only_its_group(certs, server):
    other_client = ssl.create_default_context(cafile=certs.ca)
    assert handshake(server, other_client) == 'TLSv1.3'

    other_client.set_ecdh_curve('prime256v1')
    with pytest.raises(ssl.SSLError):
        handshake(server, other_client)


def test_client_offers_only_its_group(certs, client):
    # A P-256-only server would work with a default client (via a retry), so
    # failing here proves the client offers nothing but X25519 - no ML-KEM.
    other_server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    other_server.load_cert_chain(certs.cert, certs.key)
    other_server.set_ecdh_curve('prime256v1')
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


def test_unreadable_server_hello_leaves_the_group_unknown():
    class Connection:  # stands in for an SSLObject
        pass

    conn = Connection()
    record = tls._record_group  # pylint: disable=protected-access

    record(conn, 'write', None, 22, 2, b'\x02\x00\x00\x01')  # truncated: no raise

    assert tls.negotiated_group(conn) is None
    assert tls.negotiated_group(None) is None
