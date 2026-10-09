import logging
import os
import ssl
import weakref

from lib.config import ConfigError

log = logging.getLogger(__name__)

# Key-exchange group for each hop in the spec's communication table. The reader
# and admin hops are pinned to classical X25519. The gateway -> cloud hop is
# not pinned (None): its groups, the post-quantum hybrid X25519MLKEM768 with an
# X25519 fallback, come from the OpenSSL config the gateway and cloud images
# load through OPENSSL_CONF, because Python 3.13 can't set them per context
# (see lib/README.md).
READER_GATEWAY = 'X25519'
GATEWAY_CLOUD = None
ADMIN_CLOUD = 'X25519'

# TLS 1.3 code points for reading the key share out of a ServerHello.
_HANDSHAKE, _SERVER_HELLO, _KEY_SHARE = 22, 2, 51
_GROUP_NAMES = {0x001D: 'X25519', 0x11EC: 'X25519MLKEM768'}

# SSLObject/SSLSocket -> the group it negotiated, recorded by _record_group().
_negotiated: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def server_context(cert: str, key: str, group: str | None) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return _restrict(context, group)


def client_context(ca: str, group: str | None) -> ssl.SSLContext:
    return _restrict(ssl.create_default_context(cafile=ca), group)


def negotiated_group(ssl_object: ssl.SSLObject | ssl.SSLSocket | None) -> str | None:
    """The key-exchange group of a TLS connection, or None if unknown."""
    if ssl_object is None:
        return None
    if hasattr(ssl_object, 'group'):  # Python 3.15+
        return ssl_object.group()
    return _negotiated.get(ssl_object)


def is_post_quantum(group: str | None) -> bool | None:
    """Whether a key-exchange group includes ML-KEM, or None if unknown."""
    return None if group is None else 'MLKEM' in group.upper()


def _restrict(context: ssl.SSLContext, group: str | None) -> ssl.SSLContext:
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    if group is None:
        _check_openssl_conf()
    else:
        # Offer and accept only this group, overriding the OpenSSL config.
        # Without it OpenSSL >= 3.5 silently negotiates the hybrid
        # X25519MLKEM768 whenever both ends support it.
        context.set_ecdh_curve(group)
    if not hasattr(ssl.SSLObject, 'group'):
        # Python 3.13 can't report the negotiated group (SSLObject.group() is
        # new in 3.15), so read it from the ServerHello through CPython's debug
        # hook. To be removed with the move to 3.15 (see README.md).
        context._msg_callback = _record_group  # pylint: disable=protected-access
    return context


def _check_openssl_conf() -> None:
    path = os.environ.get('OPENSSL_CONF')
    if path is None:
        log.warning('OPENSSL_CONF is not set: key exchange uses OpenSSL defaults')
    elif not os.path.isfile(path):
        # OpenSSL silently ignores a missing config file and uses its defaults.
        raise ConfigError(f'OPENSSL_CONF file {path} does not exist')
    else:
        log.info('key exchange groups from %s', path)


def _record_group(conn, _direction, _version, content_type, msg_type, data) -> None:
    # Servers write the ServerHello and clients read it. The last one counts: a
    # HelloRetryRequest is a ServerHello too.
    if (content_type, msg_type) != (_HANDSHAKE, _SERVER_HELLO):
        return
    try:
        _negotiated[conn] = _server_hello_group(data)
    except Exception:  # pylint: disable=broad-exception-caught
        # This runs inside OpenSSL's handshake: a status display must never be
        # able to break a connection.
        log.exception('could not read the key-exchange group')


def _server_hello_group(server_hello: bytes) -> str:
    """The group in the key_share extension of a ServerHello handshake message."""
    # Handshake header (4), legacy_version (2), random (32), then the session ID.
    pos = 38 + 1 + server_hello[38]
    pos += 2 + 1 + 2  # cipher suite, compression method, extensions length
    while pos < len(server_hello):
        extension = int.from_bytes(server_hello[pos : pos + 2])
        length = int.from_bytes(server_hello[pos + 2 : pos + 4])
        if extension == _KEY_SHARE:
            group = int.from_bytes(server_hello[pos + 4 : pos + 6])
            return _GROUP_NAMES.get(group, f'0x{group:04x}')
        pos += 4 + length
    raise ValueError('ServerHello without key_share')
