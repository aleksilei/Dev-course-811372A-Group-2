"""How long a reader waits between scans.

By default a random time between SCAN_INTERVAL_MIN and SCAN_INTERVAL_MAX
seconds (uniformly distributed), so readers and sites differ in how much
traffic they make. SCAN_INTERVAL sets a fixed interval instead, as before.
Empty values count as unset, since docker compose passes unset variables as
empty strings.
"""

import math
import os
import random
from collections.abc import Mapping
from dataclasses import dataclass

from lib.config import ConfigError

# 5 s on average, the old fixed interval, so the default stack's traffic stays the same.
DEFAULT_MIN = 2.0
DEFAULT_MAX = 8.0


@dataclass(frozen=True)
class ScanInterval:
    low: float
    high: float

    def __post_init__(self) -> None:
        for name, value in (
            ('SCAN_INTERVAL_MIN', self.low),
            ('SCAN_INTERVAL_MAX', self.high),
        ):
            if not math.isfinite(value) or value < 0:
                raise ConfigError(f'{name} must be 0 s or more, not {value:g}')
        if self.low > self.high:
            raise ConfigError(
                f'SCAN_INTERVAL_MIN ({self.low:g} s) is above SCAN_INTERVAL_MAX '
                f'({self.high:g} s)'
            )
        if self.high == 0:
            raise ConfigError('SCAN_INTERVAL_MAX must be above 0 s')

    def next(self, rng: random.Random | None = None) -> float:
        """Seconds to wait before the next scan."""
        return (rng or random).uniform(self.low, self.high)

    def __str__(self) -> str:
        if self.low == self.high:
            return f'every {self.low:g} s'
        return f'every {self.low:g}-{self.high:g} s'


def _seconds(environ: Mapping[str, str], name: str) -> float | None:
    value = environ.get(name, '').strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise ConfigError(
            f'{name} must be a number of seconds, not {value!r}'
        ) from None


def from_env(environ: Mapping[str, str] = os.environ) -> ScanInterval:
    """The scan interval from SCAN_INTERVAL or SCAN_INTERVAL_MIN/_MAX."""
    fixed = _seconds(environ, 'SCAN_INTERVAL')
    low = _seconds(environ, 'SCAN_INTERVAL_MIN')
    high = _seconds(environ, 'SCAN_INTERVAL_MAX')
    if fixed is not None:
        if low is not None or high is not None:
            raise ConfigError(
                'set either SCAN_INTERVAL (fixed) or SCAN_INTERVAL_MIN and '
                'SCAN_INTERVAL_MAX (random), not both'
            )
        if not math.isfinite(fixed) or fixed <= 0:
            raise ConfigError(f'SCAN_INTERVAL must be above 0 s, not {fixed:g}')
        return ScanInterval(fixed, fixed)
    return ScanInterval(
        DEFAULT_MIN if low is None else low, DEFAULT_MAX if high is None else high
    )
