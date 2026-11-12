# AI usage: SCRUM-36, Python 3.15 and native key-exchange groups

A paraphrased transcript of the Claude Code session (model: Claude Opus 5.5,
in the Claude desktop app) on 2026-11-12 that moved the system to Python 3.15.
The move replaced the two Python 3.13 workarounds of the ML-KEM version (see
[v2-mlkem.md](v2-mlkem.md)) with public `ssl` APIs. It records what the
developer asked for, what the assistant found and asked, what the developer
decided, and what was built and verified. Tool calls and code are summarised,
not reproduced.

Jira: SCRUM-36, under SCRUM-16 (Backend improvements sprint 2).

## 1. Task: discuss the migration first

The developer asked the assistant to:
- read the active Jira issues of the project for context;
- note that another agent was working on SCRUM-12 (stakeholder views) at the
  same time;
- discuss moving to Python 3.15, so the negotiated key exchange is read
  natively instead of through the CPython debug hook;
- not implement anything yet.

### Findings

The assistant read the root README's "Next step: Python 3.15" section, which
v2 had left as a five-step plan, together with `lib/tls.py`, the OpenSSL
configs, the tests, the Dockerfiles, CI and the version pins. Rather than
trust the plan, it checked each assumption:

- **Release status.** Python 3.15.0 was released on 2026-10-09, a week late
  after a surprise RC3; 3.15.1 and 3.15.2 followed in October.
  `python:3.15-slim` was on Docker Hub (updated 2026-11-07). The plan had
  been waiting on this.
- **The APIs.** `SSLContext.set_groups()` and `SSLObject.group()` exist in
  3.15, per the CPython issue and the developer's local Homebrew 3.15.1
  (OpenSSL 4.1).
- **A prototype.** In a scratch directory, outside the repository, the
  assistant ran in-memory handshakes with the dev certificates:

  | Server groups | Client groups | Result |
  |---|---|---|
  | `*X25519MLKEM768:*X25519` | the same | `X25519MLKEM768` |
  | `*X25519MLKEM768:*X25519` | `X25519` | `x25519` |
  | `X25519MLKEM768` | `X25519` | `NO_SUITABLE_KEY_SHARE` |
  | `X25519` | `X25519` | `x25519` |

- **Group-name spelling.** `group()` reports `x25519` in lower case but
  `X25519MLKEM768` as is, while the debug hook's own table produced
  `X25519`. v2 had left this as an open point. The API (`key_exchange`),
  the panel, and the hub, summary and e2e tests all compare the exact
  string.
  - The existing code already preferred `group()` whenever it existed, so
    running v2 on 3.15 would have shown `x25519` on the panel.
- **Tooling.** The pinned pylint 4.0.8 and astroid 4.0.4 only declared
  Python 3.14 support, as did websockets 17.1. pylint 4.1.3 (astroid 4.3.4)
  and websockets 17.4 declare 3.15.

The assistant also noted:
- Nothing changes on the wire, so 3.13 and 3.15 ends interoperate during a
  rollout.
- The SCRUM-12 work in the same checkout touched different files, apart from
  `README.md` and possibly `docker-compose.yml`, so the migration should get
  its own branch from `main`.

## 2. Planning

After SCRUM-12 was merged (PR #6), the developer asked for a plan and chose a
full move to 3.15: no 3.13 code path is kept. The assistant asked:

| Question | Options | Decision |
|---|---|---|
| The setting that replaces `OPENSSL_CONF` | Named modes `KEY_EXCHANGE=hybrid\|hybrid-only\|classical` (recommended); or a raw OpenSSL group list | **Named modes** |
| Jira | Create a task under SCRUM-16 (recommended); developer creates it; no ticket | **Create under SCRUM-16** (SCRUM-36) |
| AI-disclosure write-up | Add this file (recommended); skip | **Add it** |

The plan the developer approved also had the assistant:
- **Fail closed on a leftover `OPENSSL_CONF`.** An old override such as
  `OPENSSL_CONF=/opt/lib/openssl/hybrid-only.cnf` would point to a deleted
  file, which OpenSSL silently ignores. A cloud meant to refuse classical
  gateways would then accept them, so `lib.tls` stops the process instead.
- **Keep the old group names.** `negotiated_group()` reports `X25519` and
  `X25519MLKEM768`, so nothing above `lib.tls` changes.

## 3. Implementation

On the branch `python-315`, from `main`.

### `lib.tls`

- `KEY_EXCHANGE_MODES` maps each mode to an OpenSSL group list:
  - `hybrid` → `*X25519MLKEM768:*X25519`
  - `hybrid-only` → `X25519MLKEM768`
  - `classical` → `X25519`
- `gateway_cloud()` reads `KEY_EXCHANGE` (default `hybrid`) and logs the
  mode. It raises `ConfigError` for an unknown mode and for a set
  `OPENSSL_CONF`. It replaces the `GATEWAY_CLOUD = None` constant at its four
  call sites (gateway, cloud, the integration test and the e2e probe).
- Every context calls `set_groups()`. The reader and admin hops stay pinned
  to `X25519`.
- `negotiated_group()` is now `SSLObject.group()` with the canonical names.
  Removed:
  - the debug hook (`_record_group()`), the ServerHello parser
    (`_server_hello_group()`) and its `WeakKeyDictionary`;
  - `_check_openssl_conf()`.
- Deleted `lib/openssl/`.

### Configuration, runtime and CI

- `KEY_EXCHANGE` replaces `OPENSSL_CONF` in:
  - `docker-compose.yml`: `gateway-2` is `classical`, and the cloud's
    commented switch is `hybrid-only`;
  - `tests/e2e/compose.hybrid-only.yml`;
  - the classical sites of the scaled stack (`lib.topology`).
- `python:3.15-slim` in the three Dockerfiles, whose `ENV OPENSSL_CONF` lines
  went.
- Version pins:
  - `PYTHON ?= python3.15` in the `Makefile`;
  - `requires-python = ">=3.15"` and websockets 17.4 in `lib/pyproject.toml`;
  - pylint 4.1.3 and astroid 4.3.4.
- CI: the test container and `setup-python` in `pr.yml` and `release.yml` are
  on 3.15.

### Tests

- Deleted `tests/unit/lib/tls_peer.py`. The key-exchange matrix needed one
  process per end because of the process-wide `OPENSSL_CONF`; it now runs
  in-process, with both ends reporting the group through `negotiated_group()`.
- The `v1` (before ML-KEM) column folded into `classical`, which offers the
  same group on the wire.
- New tests:
  - each `KEY_EXCHANGE` mode and the default;
  - an unknown mode and a leftover `OPENSSL_CONF` are errors;
  - a real classical handshake reports `X25519`, not `x25519`;
  - unknown group names pass through;
  - the group is unknown before a handshake;
  - the pinned hops refuse a hybrid-only client.
- Removed: the ServerHello, debug-hook and missing-config-file tests.

### Docs

- Root README: the implementation decisions and risks use `KEY_EXCHANGE`, and
  the "Next step: Python 3.15" section became a short "Python 3.15" note on
  what changed and on interop.
- `lib/README.md`: the TLS section rewritten around the modes, with the
  matrix and the naming rule.
- The gateway and cloud READMEs: `KEY_EXCHANGE` in place of `OPENSSL_CONF`.

### Verification

- **Lint and tests.** On the developer's Python 3.15.1 (OpenSSL 4.1),
  `make lint` rated 10.00/10 and `make test` passed 209 tests, the ML-KEM
  matrix included (nothing skipped).
- **Images.** All three report Python 3.15.2 with OpenSSL 3.5.7, which has
  ML-KEM.
- **Misconfiguration.** Each of these stopped the container at startup with a
  `ConfigError` naming the problem:
  - `KEY_EXCHANGE=hybird` on a gateway;
  - `KEY_EXCHANGE=quantum` on the cloud;
  - a leftover `OPENSSL_CONF=/opt/lib/openssl/hybrid-only.cnf`.

  With no setting, the cloud logged `hybrid (*X25519MLKEM768:*X25519)`.
- **E2E.** The first `make e2e` run couldn't create its networks: the
  developer's scaled stack held the reader-VLAN subnet. The assistant asked
  before stopping it; the developer chose to stop it and leave it off. Then
  all 11 e2e tests passed, including:
  - the classical `gateway-2` fallback;
  - the hybrid-only cloud refusing it;
  - the per-hop probe.
- **Live stack (`make run`).**
  - `/api/gateways` listed `gw-1` as `X25519MLKEM768` (post-quantum) and
    `gw-2` as `X25519` (upper case, classical).
  - `/api/summary` was amber with readiness 0.5 and `gw-2` as the classical
    gateway.
  - The logs showed the same groups on both ends.
- **Browser.** The browser pane refused the panel's dev-CA certificate, as
  in v2, so nobody saw the panel rendered in a browser this session. The
  panel draws from those two API endpoints.

## Where the developer steered

- Asked for a discussion first, with no implementation, while another agent
  finished SCRUM-12.
- Chose a full move to 3.15 over keeping a 3.13 path.
- Chose named modes, a Jira task and this write-up.
- Approved stopping the scaled stack for the e2e tests and leaving it off.
- Renamed this write-up from `v3-python315.md` to `SCRUM-36.md`, after the
  assistant noticed that another session had started naming them per ticket
  (`SCRUM-6.md` … `SCRUM-32.md`, kept out of this change).

## Decisions the assistant made on its own

- Checking the release status, the APIs and the group spelling with a scratch
  prototype rather than relying on the v2 plan.
- Failing closed on a leftover `OPENSSL_CONF`.
- Keeping the old group names in `negotiated_group()` instead of changing the
  API.
- Bumping only the dev tools that didn't declare 3.15 support.
