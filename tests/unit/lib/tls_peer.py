"""One end of a TLS handshake for test_tls.py, in a process of its own because
the gateway -> cloud groups come from the process-wide OPENSSL_CONF.

    python tls_peer.py server <cert> <key> <group or ->
        prints its port, then the key-exchange group of the connection
    python tls_peer.py client <ca> <port> <group or ->
        prints the key-exchange group of the connection

Each end prints the group as lib.tls.negotiated_group() reports it, and
nothing if the handshake failed.
"""

import socket
import sys

from lib import tls


def serve(cert: str, key: str, group: str | None) -> None:
    context = tls.server_context(cert, key, group)
    with socket.create_server(('127.0.0.1', 0)) as listener:
        listener.settimeout(10)
        print(listener.getsockname()[1], flush=True)
        conn, _ = listener.accept()
        try:
            with context.wrap_socket(conn, server_side=True) as tls_conn:
                print(tls.negotiated_group(tls_conn))
        except OSError:  # includes ssl.SSLError
            pass


def connect(ca: str, port: int, group: str | None) -> None:
    context = tls.client_context(ca, group)
    try:
        with (
            socket.create_connection(('127.0.0.1', port), timeout=10) as sock,
            context.wrap_socket(sock, server_hostname='localhost') as tls_conn,
        ):
            print(tls.negotiated_group(tls_conn))
            # Close only after the server, which is still finishing its side.
            tls_conn.recv(1)
    except OSError:  # includes ssl.SSLError
        pass


if __name__ == '__main__':
    role, path, arg, pinned = sys.argv[1:]
    if role == 'server':
        serve(path, arg, None if pinned == '-' else pinned)
    else:
        connect(path, int(arg), None if pinned == '-' else pinned)
