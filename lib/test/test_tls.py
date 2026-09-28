import socket
import ssl
import threading

import pytest

from lib import tls


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


@pytest.fixture(name='server')
def server_fixture(certs):
    return tls.server_context(certs.cert, certs.key, tls.READER_GATEWAY)


@pytest.fixture(name='client')
def client_fixture(certs):
    return tls.client_context(certs.ca, tls.READER_GATEWAY)


def test_every_hop_is_classical_for_now():
    assert tls.READER_GATEWAY == tls.GATEWAY_CLOUD == tls.ADMIN_CLOUD == 'X25519'


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
