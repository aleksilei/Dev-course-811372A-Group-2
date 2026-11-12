# AI usage: SCRUM-35, readers scan at random intervals

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-12 that implemented Jira
ticket SCRUM-35, "Readers scan at random intervals within a configurable
range". It records what the developer asked for, what the assistant decided,
what was built and verified, and where the assistant was wrong. Tool calls
and code are summarised, not reproduced. The ticket itself was written by the
assistant earlier in the same session (see [SCRUM-12.md](SCRUM-12.md),
section 5).

## 1. Task

The developer asked for SCRUM-35 on a new branch, and pointed out that the
git log had changed. The assistant fetched and found two merges since the
last ticket: the Python 3.15 migration (SCRUM-36, PR #7, done in another
session) and the disclosure documents of this session. It pulled `main` and
branched `reader-random-interval` from it.

The ticket: every reader scanned exactly every `SCAN_INTERVAL` seconds, so all
readers and sites made the same traffic, and a traffic-weighted readiness
score (SCRUM-11) would look the same as the share of PQC gateways. DoD:

- a uniformly random wait between `SCAN_INTERVAL_MIN` and `SCAN_INTERVAL_MAX`,
  with invalid values failing at startup with a clear error;
- `SCAN_INTERVAL` still meaning a fixed interval, so the e2e tests and existing
  setups keep working;
- different ranges per site in `make run-scaled`;
- unit tests and the reader README.

## 2. Design

The assistant read the reader, its tests, the compose file, `lib.topology`,
the e2e harness and how other components report bad configuration (`lib.tls`
raises `ConfigError` at startup, so the reader does the same). It did not ask
the developer anything; the decisions it took on its own:

| Question | Decision |
|---|---|
| Default when nothing is set | **2-8 s**: 5 s on average, the old fixed interval, so the default stack's traffic stays the same |
| `SCAN_INTERVAL` together with `SCAN_INTERVAL_MIN`/`_MAX` | **An error**, rather than one silently winning |
| Only one end of the range set | The other keeps its default; a minimum above the default maximum is then an error |
| A wait of 0 s | Allowed as a minimum, **rejected as the whole range** or as `SCAN_INTERVAL`, since the reader would scan without pausing |
| Empty values | **Count as unset**: `docker-compose.yml` passes unset variables as `${VAR:-}`, an empty string |
| Scaled sites' ranges | Taking turns: busy 1-3 s, normal 2-8 s, quiet 5-15 s, very quiet 10-30 s (up to 10x the traffic) |

## 3. Implementation

- `reader/interval.py`: a `ScanInterval(low, high)` that validates itself and
  draws each wait with `random.uniform`, and `from_env()` that reads the three
  variables.
- `reader/scanner.py`: the scan loop moved into `scan_forever()`, with the
  sleep function as a parameter so a test can record the waits. The reader
  logs its interval at startup ("scanning every 1-3 s").
- `docker-compose.yml` passes all three variables, empty when unset, instead
  of `SCAN_INTERVAL` with a default of 5. `lib.topology` gives each site's
  readers their site's `SCAN_INTERVAL_MIN`/`_MAX`.
- Tests: the interval settings (defaults, one end set, fixed, empty values,
  both kinds set, non-numbers, negative, infinite, NaN, minimum above maximum,
  zero), that waits stay in the range and spread evenly across it, that the
  scan loop waits a new time after every scan, and the scaled sites' ranges.
- The reader README got a "Scan interval" section; the root README describes
  the scaled sites' ranges.

## 4. Verification and fixes

- `make test`: 239 passed; `make lint` clean; `make e2e`: 11 passed, still on
  the fixed `SCAN_INTERVAL=1`. The developer's scaled stack was running on
  the same ports, so the assistant stopped it for the e2e run and started it
  again afterwards with the new images.
- On the scaled stack every reader logged its range, and over two minutes the
  sites made the expected number of scans:

  | Range | Expected (8 readers, 120 s) | Measured |
  |---|---|---|
  | 1-3 s | 480 | 476-479 |
  | 2-8 s | 192 | 192-194 |
  | 5-15 s | 96 | 96-97 |
  | 10-30 s | 48 | 48-50 |

  A first, quicker count came out at about two thirds of these for every site,
  because the stack had not yet been up for the whole window; the ratios were
  already right.
- `/api/summary` now reported classical gateways carrying 29% of the traffic
  while being 25% of the gateways, and `gw-s9`, a busy site, 20% on its own:
  the difference SCRUM-11 needs.
- Starting the reader with bad values exited with code 1 and the error. The
  first check of this showed the wrong errors because the assistant's own
  shell loop (zsh) didn't split the variables; it reran it correctly. It then
  noticed that `SCAN_INTERVAL=-1` was reported as a bad "minimum", and changed
  every message to name the variable that was set.

## 5. Result

The developer asked for the commit together with this write-up.

## Where the developer steered

- Pointed out the new commits on `main` before the work started, and asked for
  a new branch.
- Asked for this write-up with the commit.

## Decisions the assistant made on its own

- Everything in the design table above.
- Stopping and restarting the developer's scaled stack for the e2e run and the
  live check.
- Testing the loop through an injected sleep instead of patching
  `asyncio.sleep`.
