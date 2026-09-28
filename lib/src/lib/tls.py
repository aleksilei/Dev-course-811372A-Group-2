import ssl

# Key-exchange group for each hop in the spec's communication table. Every hop
# is classical for now; v2 moves GATEWAY_CLOUD to the post-quantum hybrid
# 'X25519MLKEM768' (see lib/README.md).
READER_GATEWAY = 'X25519'
GATEWAY_CLOUD = 'X25519'
ADMIN_CLOUD = 'X25519'


def server_context(cert: str, key: str, group: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return _restrict(context, group)


def client_context(ca: str, group: str) -> ssl.SSLContext:
    return _restrict(ssl.create_default_context(cafile=ca), group)


def _restrict(context: ssl.SSLContext, group: str) -> ssl.SSLContext:
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    # Offer and accept only this group. Without it OpenSSL >= 3.5 silently
    # negotiates the hybrid X25519MLKEM768 whenever both ends support it.
    context.set_ecdh_curve(group)
    return context
