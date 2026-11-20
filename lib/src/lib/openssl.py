"""The OpenSSL version each device runs, and whether it is vulnerable (SCRUM-51).

Readers and gateways send their version in the OPENSSL_HEADER handshake
header. Gateways relay their readers' versions in the reader report. The
cloud checks each version, and its own, against ADVISORIES. Like device IDs,
a reported version is taken on trust, because devices are not authenticated.

Fails closed: a connected device that reports no version, or one the cloud
can't check (not OpenSSL, malformed), is assumed vulnerable to every advisory.
An old device that was never restarted onto a patch most likely runs an old
version.
"""

import logging
import re
import ssl
from dataclasses import dataclass

from lib.config import ConfigError, env

log = logging.getLogger(__name__)

OPENSSL_HEADER = 'OpenSSL-Version'

# Simulation knob: report this version instead of the one actually linked,
# e.g. "OpenSSL 3.5.8". All the images share one base image, so without it
# every device (and the cloud) would report the same version.
OVERRIDE_ENV = 'OPENSSL_VERSION_REPORTED'

# Longer reports are dropped. The real ones are ~25 characters long.
MAX_LENGTH = 64

# What an advisory breaks, so callers can tell which advisories matter to them.
ML_KEM = 'ml-kem'

Version = tuple[int, int, int]


@dataclass(frozen=True)
class Advisory:
    """Versions first <= v < fixed are affected; `affects` says what breaks."""

    name: str
    affects: str
    impact: str
    first: Version
    fixed: Version

    def text(self) -> str:
        return (
            f'{self.name}: {self.impact}. '
            f'Upgrade to OpenSSL {format_version(self.fixed)} or newer.'
        )


# Add a row for every new advisory. The ML-KEM vulnerability is the course's
# simulated event (SCRUM-45): we play along that OpenSSL before 3.5.8 is
# affected.
ADVISORIES = [
    Advisory(
        name='ML-KEM vulnerability (SCRUM-45)',
        affects=ML_KEM,
        impact='hybrid key exchange is no stronger than classical',
        first=(0, 0, 0),
        fixed=(3, 5, 8),
    ),
]

# "OpenSSL 3.5.7 9 Jun 2026", "OpenSSL 1.1.1w  11 Sep 2023" or just "3.5.8".
# Other libraries (e.g. "LibreSSL 3.8.2") are not OpenSSL and don't match.
_VERSION = re.compile(r'(?:OpenSSL )?(\d+)\.(\d+)\.(\d+)(?![\d.])')

# The fields of a device that isn't connected: nothing is known, or claimed.
UNKNOWN = {
    'openssl': None,
    'openssl_checked': None,
    'openssl_vulnerable': None,
    'openssl_affects': None,
    'openssl_advisory': None,
}


def format_version(version: Version) -> str:
    return '.'.join(str(part) for part in version)


def fixed_in(affects: str) -> str:
    """The first version fixing every advisory that breaks `affects`, e.g. '3.5.8'."""
    return format_version(max(a.fixed for a in ADVISORIES if a.affects == affects))


def local_version() -> str:
    """The version this process reports: OVERRIDE_ENV if set, else the linked one."""
    override = env(OVERRIDE_ENV, '')
    if not override:
        return ssl.OPENSSL_VERSION
    if parse(override) is None or len(override) > MAX_LENGTH:
        raise ConfigError(
            f'{OVERRIDE_ENV} must be an OpenSSL version such as "OpenSSL 3.5.8", '
            f'not {override!r}'
        )
    log.info(
        'reporting OpenSSL version %r (simulated) instead of %r',
        override,
        ssl.OPENSSL_VERSION,
    )
    return override


def reported(value: object) -> str | None:
    """A version as a device reported it, or None if missing or malformed."""
    if isinstance(value, str) and 0 < len(value) <= MAX_LENGTH:
        return value
    return None


def parse(version: str | None) -> Version | None:
    """(major, minor, patch) of an OpenSSL version string, or None if it isn't one."""
    match = None if version is None else _VERSION.match(version.strip())
    return None if match is None else tuple(int(part) for part in match.groups())


def advisories(version: str | None) -> list[Advisory] | None:
    """The advisories affecting this version, or None if it can't be checked."""
    number = parse(version)
    if number is None:
        return None
    return [a for a in ADVISORIES if a.first <= number < a.fixed]


def is_vulnerable(version: str | None) -> bool:
    """Whether any advisory affects this version; True if it can't be checked."""
    matching = advisories(version)
    return matching is None or bool(matching)


def details(version: str | None) -> dict:
    """The fields of a connected device that reported `version` (None if it
    didn't): openssl, and whether it was _checked, is _vulnerable, what that
    _affects (e.g. ML_KEM) and the _advisory text."""
    matching = advisories(version)
    if matching is None:
        reason = (
            'not reported' if version is None else 'not a version the cloud can check'
        )
        return {
            'openssl': version,
            'openssl_checked': False,
            'openssl_vulnerable': True,
            'openssl_affects': sorted({a.affects for a in ADVISORIES}),
            'openssl_advisory': f'OpenSSL version {reason}: assumed vulnerable to '
            f'every advisory ({", ".join(a.name for a in ADVISORIES)}).',
        }
    return {
        'openssl': version,
        'openssl_checked': True,
        'openssl_vulnerable': bool(matching),
        'openssl_affects': sorted({a.affects for a in matching}),
        'openssl_advisory': ' '.join(a.text() for a in matching) or None,
    }


def breaks(device: dict | None, affects: str) -> bool:
    """Whether a device's details() say its OpenSSL breaks `affects`."""
    return affects in ((device or {}).get('openssl_affects') or [])


def weakens_hybrid(gateway: dict, cloud: dict | None) -> bool:
    """Whether a gateway's hybrid key exchange is no stronger than classical:
    the OpenSSL at either end of its link, the gateway's or the cloud's
    (details(), None if left out), breaks ML-KEM."""
    return gateway.get('post_quantum') is True and (
        breaks(cloud, ML_KEM) or breaks(gateway, ML_KEM)
    )
