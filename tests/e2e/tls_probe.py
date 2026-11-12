"""Run inside a container of the stack (see Stack.probe()):

    python - <host> <port> < tls_probe.py

Makes one TLS handshake with the server and prints the key-exchange group it
picked. The client offers the gateway -> cloud groups of the container's
KEY_EXCHANGE: in the gateway image by default (hybrid), X25519MLKEM768 and
X25519.
"""

import socket
import sys

from lib import tls

host, port = sys.argv[1], int(sys.argv[2])
context = tls.client_context('/certs/ca.pem', tls.gateway_cloud())
with (
    socket.create_connection((host, port), timeout=5) as sock,
    context.wrap_socket(sock, server_hostname=host) as conn,
):
    print(tls.negotiated_group(conn))
