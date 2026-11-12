import random

import pytest

from lib.config import ConfigError
from reader.interval import DEFAULT_MAX, DEFAULT_MIN, ScanInterval, from_env


def test_defaults_to_a_random_range_averaging_the_old_five_seconds():
    assert from_env({}) == ScanInterval(DEFAULT_MIN, DEFAULT_MAX)
    assert (DEFAULT_MIN + DEFAULT_MAX) / 2 == 5


def test_reads_the_range():
    environ = {'SCAN_INTERVAL_MIN': '0.5', 'SCAN_INTERVAL_MAX': '30'}

    assert from_env(environ) == ScanInterval(0.5, 30)


@pytest.mark.parametrize(
    ('environ', 'expected'),
    [
        ({'SCAN_INTERVAL_MIN': '4'}, ScanInterval(4, DEFAULT_MAX)),
        ({'SCAN_INTERVAL_MAX': '20'}, ScanInterval(DEFAULT_MIN, 20)),
    ],
)
def test_an_unset_end_of_the_range_keeps_its_default(environ, expected):
    assert from_env(environ) == expected


def test_scan_interval_means_a_fixed_interval():
    interval = from_env({'SCAN_INTERVAL': '1'})

    assert interval == ScanInterval(1, 1)
    assert interval.next() == 1


def test_empty_values_count_as_unset():
    """docker compose passes ${VAR:-} as an empty string."""
    environ = {'SCAN_INTERVAL': '', 'SCAN_INTERVAL_MIN': ' ', 'SCAN_INTERVAL_MAX': ''}

    assert from_env(environ) == ScanInterval(DEFAULT_MIN, DEFAULT_MAX)


def test_fixed_and_range_together_is_an_error():
    with pytest.raises(ConfigError, match='either SCAN_INTERVAL'):
        from_env({'SCAN_INTERVAL': '5', 'SCAN_INTERVAL_MAX': '10'})


@pytest.mark.parametrize(
    'name', ['SCAN_INTERVAL', 'SCAN_INTERVAL_MIN', 'SCAN_INTERVAL_MAX']
)
@pytest.mark.parametrize('value', ['fast', '5s', '1,5'])
def test_a_value_that_is_not_a_number_names_its_variable(name, value):
    with pytest.raises(ConfigError, match=f'{name} must be a number'):
        from_env({name: value})


@pytest.mark.parametrize(
    ('environ', 'message'),
    [
        ({'SCAN_INTERVAL': '-1'}, 'SCAN_INTERVAL must be above 0 s, not -1'),
        ({'SCAN_INTERVAL': '0'}, 'SCAN_INTERVAL must be above 0 s, not 0'),
        ({'SCAN_INTERVAL': 'inf'}, 'SCAN_INTERVAL must be above 0 s'),
        ({'SCAN_INTERVAL_MIN': '-1'}, 'SCAN_INTERVAL_MIN must be 0 s or more, not -1'),
        ({'SCAN_INTERVAL_MAX': 'inf'}, 'SCAN_INTERVAL_MAX must be 0 s or more'),
        ({'SCAN_INTERVAL_MIN': 'nan'}, 'SCAN_INTERVAL_MIN must be 0 s or more'),
        (
            {'SCAN_INTERVAL_MIN': '9', 'SCAN_INTERVAL_MAX': '3'},
            r'SCAN_INTERVAL_MIN \(9 s\) is above SCAN_INTERVAL_MAX \(3 s\)',
        ),
        (
            {'SCAN_INTERVAL_MIN': '0', 'SCAN_INTERVAL_MAX': '0'},
            'SCAN_INTERVAL_MAX must be above 0 s',
        ),
    ],
)
def test_invalid_ranges_are_errors(environ, message):
    with pytest.raises(ConfigError, match=message):
        from_env(environ)


def test_a_zero_minimum_is_allowed():
    assert from_env({'SCAN_INTERVAL_MIN': '0'}) == ScanInterval(0, DEFAULT_MAX)


def test_waits_stay_in_the_range_and_spread_across_it():
    interval = ScanInterval(2, 8)
    rng = random.Random(35)

    waits = [interval.next(rng) for _ in range(2000)]

    assert all(2 <= wait <= 8 for wait in waits)
    # Uniform: about a sixth of the waits in each second of the range.
    for start in range(2, 8):
        share = sum(start <= wait < start + 1 for wait in waits) / len(waits)
        assert share == pytest.approx(1 / 6, abs=0.04)
    assert sum(waits) / len(waits) == pytest.approx(5, abs=0.2)


@pytest.mark.parametrize(
    ('interval', 'text'),
    [(ScanInterval(1, 1), 'every 1 s'), (ScanInterval(2, 8.5), 'every 2-8.5 s')],
)
def test_describes_itself_for_the_startup_log(interval, text):
    assert str(interval) == text
