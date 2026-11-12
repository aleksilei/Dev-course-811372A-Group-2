import logging
import os
import ssl

from lib.config import ConfigError, env

log = logging.getLogger(__name__)

# Key-exchange groups for each hop in the spec's communication table, as
# OpenSSL group lists for SSLContext.set_groups(). The reader and admin hops
# are pinned to classical X25519. The gateway -> cloud hop is chosen per
# deployment with KEY_EXCHANGE: see gateway_cloud().
READER_GATEWAY = 'X25519'
ADMIN_CLOUD = 'X25519'

# KEY_EXCHANGE -> the groups the gateway -> cloud hop offers and accepts. The *
# makes a client send a key share for both groups in its first message, so a
# classical peer costs no extra round trip (HelloRetryRequest).
KEY_EXCHANGE_MODES = {
    'hybrid': '*X25519MLKEM768:*X25519',  # post-quantum, classical fallback
    'hybrid-only': 'X25519MLKEM768',  # refuses peers without ML-KEM
    'classical': 'X25519',  # what software from before ML-KEM offers
}

# OpenSSL spells some groups in lower case (x25519); report the names above.
_GROUP_NAMES = {name.lower(): name for name in ('X25519', 'X25519MLKEM768')}


def gateway_cloud() -> str:
    """The groups of the gateway -> cloud hop, from KEY_EXCHANGE (default hybrid)."""
    if 'OPENSSL_CONF' in os.environ:
        # The OpenSSL configs of Python 3.13 are gone, and OpenSSL silently
        # ignores a missing config file: a leftover hybrid-only.cnf would
        # quietly accept classical gateways.
        raise ConfigError(
            'OPENSSL_CONF is no longer used: set KEY_EXCHANGE to one of '
            + ', '.join(KEY_EXCHANGE_MODES)
        )
    mode = env('KEY_EXCHANGE', 'hybrid')
    if mode not in KEY_EXCHANGE_MODES:
        raise ConfigError(
            f'KEY_EXCHANGE must be one of {", ".join(KEY_EXCHANGE_MODES)}, not {mode!r}'
        )
    groups = KEY_EXCHANGE_MODES[mode]
    log.info('gateway -> cloud key exchange: %s (%s)', mode, groups)
    return groups


def server_context(cert: str, key: str, groups: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return _restrict(context, groups)


def client_context(ca: str, groups: str) -> ssl.SSLContext:
    return _restrict(ssl.create_default_context(cafile=ca), groups)


def negotiated_group(ssl_object: ssl.SSLObject | ssl.SSLSocket | None) -> str | None:
    """The key-exchange group of a TLS connection, or None if unknown."""
    group = None if ssl_object is None else ssl_object.group()
    return None if group is None else _GROUP_NAMES.get(group.lower(), group)


def is_post_quantum(group: str | None) -> bool | None:
    """Whether a key-exchange group includes ML-KEM, or None if unknown."""
    return None if group is None else 'MLKEM' in group.upper()


def _restrict(context: ssl.SSLContext, groups: str) -> ssl.SSLContext:
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    # Offer and accept only these groups. Without it OpenSSL >= 3.5 silently
    # negotiates the hybrid X25519MLKEM768 whenever both ends support it.
    context.set_groups(groups)
    return context
