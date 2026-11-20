import re

import pytest

from lib import openssl
from lib.topology import pinned_openssl


@pytest.mark.parametrize(
    ('version', 'expected'),
    [
        ('OpenSSL 3.5.7 9 Jun 2026', (3, 5, 7)),
        ('OpenSSL 1.1.1w  11 Sep 2023', (1, 1, 1)),
        ('OpenSSL 4.1.0 23 Oct 2026', (4, 1, 0)),
        ('3.5.8', (3, 5, 8)),
        (' OpenSSL 3.5.8 ', (3, 5, 8)),
        ('LibreSSL 3.8.2', None),  # not OpenSSL
        ('OpenSSL 3.5', None),
        ('OpenSSL 3.5.7.1', None),
        ('', None),
        (None, None),
    ],
)
def test_parses_openssl_version_strings(version, expected):
    assert openssl.parse(version) == expected


@pytest.mark.parametrize(
    ('version', 'vulnerable'),
    [
        ('OpenSSL 3.5.7 9 Jun 2026', True),  # what the images run
        ('OpenSSL 3.5.0 8 Apr 2025', True),
        ('OpenSSL 3.0.13 30 Jan 2024', True),
        ('OpenSSL 1.1.1w  11 Sep 2023', True),
        ('OpenSSL 3.5.8', False),  # the first fixed version
        ('OpenSSL 3.6.0 1 Oct 2025', False),
        ('OpenSSL 4.1.0 23 Oct 2026', False),
    ],
)
def test_everything_before_3_5_8_has_the_ml_kem_advisory(version, vulnerable):
    assert openssl.is_vulnerable(version) is vulnerable
    details = openssl.details(version)
    assert details['openssl_checked'] is True
    assert details['openssl_vulnerable'] is vulnerable
    assert openssl.breaks(details, openssl.ML_KEM) is vulnerable
    assert (details['openssl_advisory'] is not None) is vulnerable


def test_details_name_the_advisory_and_its_fix():
    details = openssl.details('OpenSSL 3.5.7 9 Jun 2026')

    assert details == {
        'openssl': 'OpenSSL 3.5.7 9 Jun 2026',
        'openssl_checked': True,
        'openssl_vulnerable': True,
        'openssl_affects': [openssl.ML_KEM],
        'openssl_advisory': 'ML-KEM vulnerability (SCRUM-45): hybrid key exchange is '
        'no stronger than classical. Upgrade to OpenSSL 3.5.8 or newer.',
    }
    assert openssl.fixed_in(openssl.ML_KEM) == '3.5.8'


@pytest.mark.parametrize('version', [None, 'LibreSSL 3.8.2', 'patched'])
def test_a_version_that_cannot_be_checked_is_assumed_vulnerable(version):
    # Fails closed: e.g. an old gateway never restarted onto a patch.
    details = openssl.details(version)

    assert openssl.is_vulnerable(version) is True
    assert details['openssl_checked'] is False
    assert details['openssl_vulnerable'] is True
    assert openssl.breaks(details, openssl.ML_KEM)
    assert 'assumed vulnerable' in details['openssl_advisory']


def test_an_advisory_only_breaks_what_it_affects():
    advisory = openssl.Advisory(
        'X.509 bug', 'x509', 'certificates', (3, 0, 0), (9, 0, 0)
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(openssl, 'ADVISORIES', [*openssl.ADVISORIES, advisory])
        details = openssl.details('OpenSSL 3.5.8')

    assert details['openssl_vulnerable'] is True
    assert details['openssl_affects'] == ['x509']
    assert not openssl.breaks(details, openssl.ML_KEM)


def test_nothing_is_known_or_claimed_about_a_device_that_is_not_connected():
    assert set(openssl.UNKNOWN.values()) == {None}
    assert not openssl.breaks(openssl.UNKNOWN, openssl.ML_KEM)
    assert not openssl.breaks(None, openssl.ML_KEM)


@pytest.mark.parametrize(
    'value', [None, 7, ['OpenSSL 3.5.7'], '', 'x' * (openssl.MAX_LENGTH + 1)]
)
def test_malformed_reports_are_dropped(value):
    assert openssl.reported(value) is None


def test_a_report_is_kept_as_sent():
    assert openssl.reported('OpenSSL 3.5.7 9 Jun 2026') == 'OpenSSL 3.5.7 9 Jun 2026'


def test_the_pinned_openssl_of_the_image_variants_has_the_fix():
    # openssl/openssl.env: what the -openssl<version> images build (SCRUM-55).
    pinned = pinned_openssl()

    assert openssl.is_vulnerable(pinned['OPENSSL_VERSION']) is False
    assert re.fullmatch('[0-9a-f]{64}', pinned['OPENSSL_SHA256'])


PATCHED = openssl.details('OpenSSL 3.5.8')
VULNERABLE = openssl.details('OpenSSL 3.5.7 9 Jun 2026')


@pytest.mark.parametrize(
    ('gateway', 'cloud', 'weakened'),
    [
        ({'post_quantum': True, **PATCHED}, PATCHED, False),
        ({'post_quantum': True, **VULNERABLE}, PATCHED, True),  # its own end
        ({'post_quantum': True, **PATCHED}, VULNERABLE, True),  # the cloud's end
        ({'post_quantum': True, **openssl.details(None)}, PATCHED, True),  # assumed
        ({'post_quantum': True, **PATCHED}, None, False),  # cloud left out
        ({'post_quantum': False, **VULNERABLE}, VULNERABLE, False),  # no ML-KEM used
        ({'post_quantum': None, **VULNERABLE}, VULNERABLE, False),
    ],
)
def test_hybrid_is_weakened_by_a_vulnerable_ml_kem_at_either_end(
    gateway, cloud, weakened
):
    assert openssl.weakens_hybrid(gateway, cloud) is weakened
