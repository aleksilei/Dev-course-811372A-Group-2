# AI usage: v2, ML-KEM on the gateway → cloud hop

A paraphrased transcript of the Claude Code session (model: Claude Opus 5.5,
in the Claude desktop app) on 2026-10-09 that added post-quantum hybrid key
exchange (ML-KEM) to the gateway → cloud hop, with a classical fallback, a
key-exchange status on the control panel, and a documented path to Python
3.15. It records what the developer asked for, what the assistant found and
asked, what the developer decided, and what was built and verified. Tool calls
and code are summarised, not reproduced.

The work was merged as PR #1 (`mlkem-gateway-cloud`). The codebase has changed
since then: the tests moved into one `tests/` tree, compose end-to-end tests,
a GitHub Actions pipeline and a release workflow were added, and the cloud
README was updated. File paths and test counts here describe the state as of
this session, not the current one.

## 1. Task: can ML-KEM be a drop-in?

The developer asked the assistant to read the codebase and assess whether
ML-KEM could be added to the gateway → cloud hop as a drop-in replacement.
Their constraints:

- The reader → gateway hop staying classical is a known limitation, because
  the reader might not have the compute for ML-KEM.
- There must be a fallback when either the cloud or a gateway doesn't support
  ML-KEM, e.g. a fleet where new gateways support it and older deployments
  don't. Both must keep working.
- Ask questions for executive decisions.

### Findings

The assistant read the READMEs, the spec, `lib/tls.py` and its tests, the
gateway and cloud code, the Dockerfiles and the compose file. v1 pinned every
hop to classical X25519 with `SSLContext.set_ecdh_curve()`, and
`lib/README.md` already sketched a v2 plan: set
`GATEWAY_CLOUD = 'X25519MLKEM768'`, then either move to Python 3.15's
`set_groups()` or load an `OPENSSL_CONF` on older Pythons. Rather than trust
that plan, the assistant tested each part of it:

- `set_ecdh_curve('X25519MLKEM768')` raises `ValueError` on both Python 3.13
  and 3.14, and neither has `set_groups()`.
- The images run OpenSSL 3.5.7 (the dev machine 3.6.3). That version has
  ML-KEM and negotiates `X25519MLKEM768` by default.
- It used `openssl s_client`/`s_server` against the real `lib.tls` contexts,
  with the v1 code standing in for "old" software, to build a fallback
  matrix:
  - new ↔ new negotiates the hybrid;
  - a new gateway with an old cloud, and an old gateway with a new cloud,
    both fall back to X25519;
  - an old gateway against a hybrid-only cloud fails ("no suitable key
    share").
- A plain group list (`X25519MLKEM768:X25519`) costs a HelloRetryRequest round
  trip against an old cloud. OpenSSL 3.5's `*X25519MLKEM768:*X25519` avoids it
  by sending both key shares in the first message.
- Python 3.15 was only available as `3.15-rc-slim` (rc3) on Docker Hub, with
  no Homebrew formula. The 3.15 documentation and source confirmed
  `set_groups()`, `SSLSocket.group()` and `SSLObject.group()`; the last is the
  one websockets' asyncio transport exposes.
- An `openssl.cnf` loaded through `OPENSSL_CONF` works on 3.13. Contexts
  pinned with `set_ecdh_curve()` still override it, so the reader and admin
  hops stay classical inside the same process.

**Verdict:** a drop-in at the TLS layer, since nothing above `ssl.SSLContext`
changes. It isn't the one-line change the README described, though, for
three reasons:

- pinning a single hybrid group breaks the fallback;
- 3.13 can't set hybrid groups per context;
- 3.15 wasn't final.

The assistant also listed security notes for the team's risk write-up:

- TLS 1.3's signed transcript prevents a downgrade between two upgraded ends.
- Connections that fall back to X25519 remain open to record-now,
  decrypt-later attacks.
- Certificates stay ECDSA P-256: ML-KEM covers confidentiality, not
  authentication.
- The hybrid adds about 1.2 KB per handshake direction.
- On the reader hop, ML-KEM-768 is cheap to compute, so the real constraints
  there are more likely the handshake size and TLS-stack support than CPU.

### Decisions

| Question | Assistant's recommendation | Decision |
|---|---|---|
| Runtime path | Python 3.15 (per-context `set_groups()`, negotiated group visible) | **Stay on 3.13 with `OPENSSL_CONF`** |
| Policy for gateways or clouds that only do X25519 | Allow them by default, plus a hybrid-only switch | As recommended |
| Where to show the negotiated group (needs 3.15) | Offered logs, panel, per access event | No preference; skipped, since 3.13 can't read it |
| Show a mixed fleet in docker-compose | Add a legacy gateway | As recommended |

## 2. Implementation

### OpenSSL configs, and making them fail closed

Three configs went into `lib/openssl/`:

- `hybrid.cnf` (`*X25519MLKEM768:*X25519`) is the image default.
- `hybrid-only.cnf` refuses classical peers.
- `classical.cnf` is for rollback and the demo's legacy gateway.

Before relying on `OPENSSL_CONF`, the assistant tested how it fails. OpenSSL
silently ignores a missing file, and also a typo in `Groups`. With a typo, a
server accepted a P-256 client, which would quietly defeat hybrid-only. The
fixes:

- Each config sets `config_diagnostics = 1`, which makes errors fatal when a
  context is created.
- `lib.tls` raises `ConfigError` if `OPENSSL_CONF` names a missing file.
- `lib.tls` logs a warning if `OPENSSL_CONF` isn't set (e.g. venv runs, which
  then get OpenSSL's built-in list).

### `lib.tls`

`GATEWAY_CLOUD` became `None`, meaning not pinned in code: its groups come
from the config. The reader and admin hops stay pinned to X25519.

### Tests

The version matrix needs a different config on each side, so each end runs in
its own process (`lib/test/tls_peer.py`) under its own `OPENSSL_CONF`.
Python 3.13 can't report the negotiated group, so the server end read it from
the ServerHello through CPython's private `_msg_callback` debug hook. The
tests cover:

- 10 gateway × cloud pairs;
- that pinned hops stay classical in a process running `hybrid.cnf`;
- that a missing config file is an error.

They skip on OpenSSL < 3.5.

A mutation check confirmed the matrix can fail: flipping the preference order
in `hybrid.cnf` failed it, and so did a typo in the file. While the assistant
restored the file afterwards, an interactive `cp` alias silently declined to
overwrite it. The assistant caught this from the output and restored the file
with `/bin/cp -f` before continuing.

### Deployment, demo and docs

- The gateway and cloud Dockerfiles set
  `OPENSSL_CONF=/opt/lib/openssl/hybrid.cnf`.
- `docker-compose.yml` gained:
  - `gateway-2` (`gw-2`, static IP `10.10.0.11`, `classical.cnf`), standing in
    for a gateway that hasn't been upgraded;
  - `reader-5` (`rd-5`, `loading-dock`, group `employees`) behind it;
  - a commented `hybrid-only.cnf` line on the cloud.
- Supporting changes for the demo:
  - a `gateway-2` certificate;
  - seed data and DB tests for `gw-2` and `rd-5`;
  - `make certs` now keyed on `gateway-2.pem`, so older setups regenerate
    their certificates.
- Documentation:
  - The TLS section of `lib/README.md` was rewritten, with the gateway ×
    cloud outcome table.
  - The gateway and cloud READMEs gained `OPENSSL_CONF` rows.
  - The root README got an updated diagram, implementation decision and
    risks, plus notes on the demo and on resetting the database.

### Verification

`make check` passed: pylint 10/10, ruff clean, 94 tests.

For Docker, the assistant ran the stack from a scratch copy of the repository
so the developer's `data/` (certificates and database) stayed untouched.

- **Default mode:** a probe inside each gateway container connected to the
  cloud and read the group actually negotiated: `gateway-1` got
  `X25519MLKEM768`, and `gateway-2` fell back to `X25519`. Both gateways were
  connected, and the access decisions behind each were correct.
- **Cloud on `hybrid-only.cnf`:**
  - `gw-2` was refused;
  - `rd-5` failed closed for keys that had passed before;
  - the panel port stayed on X25519.

The assistant pointed out the side effects for the developer:

- the next `make run` regenerates the certificates, including a new CA;
- an existing database doesn't know `rd-5`;
- the scratch build had retagged the local `dev-course/*` images.

## 3. Python 3.15 as the next step, and gateway status on the dashboard

The developer asked for two things:

- document Python 3.15 as the next step in the software's evolution;
- find out whether each gateway's encryption status could be shown on the
  cloud dashboard.

The assistant prototyped the debug hook on a live websockets server:

- The `conn` the hook receives is the same `SSLObject` that websockets exposes
  as `transport.get_extra_info('ssl_object')`.
- A `WeakKeyDictionary` drops each entry when its connection closes.
- The cost is about two extra Python calls per message.
- An exception raised inside the hook didn't break the connections; the
  status just stayed empty.

It then asked:

| Question | Options | Decision |
|---|---|---|
| How the dashboard gets each gateway's status | Now, via the private debug hook, with the code already preferring 3.15's `SSLObject.group()` (recommended); or wait for Python 3.15 | **Now via the debug hook, with the 3.15 implementation clearly documented as the next step** |

Built:

- `lib.tls`:
  - `negotiated_group(ssl_object)` uses `SSLObject.group()` when it exists and
    the hook's record otherwise;
  - `is_post_quantum(group)` checks, case-insensitively, whether the group
    includes ML-KEM;
  - the hook is installed only when `SSLObject` has no `group()`;
  - the hook never raises (it logs instead), so it can't break a handshake.
- `lib.hub`:
  - `Hub` records each client's group when it connects;
  - `connected()` now returns `key_exchange` and `post_quantum`.
- Logs: the cloud and the gateway log the group on every connection.
- Control panel:
  - a "Key exchange" column, green for the post-quantum hybrid and amber for
    classical;
  - a summary line counting the classical gateways that switching to
    hybrid-only would disconnect;
  - two new fields in `/api/gateways`.
- Tests:
  - The test peer now reports the group through the production
    `negotiated_group()` on both ends, and the test asserts the two agree.
  - Hub tests cover the hook path over real TLS, and a faked 3.15-style
    `group()`.
  - Unit tests cover the classification and the hook's guard.
  - The system test checks the panel API.

  While writing a new assertion, the assistant noticed an operator-precedence
  bug (`a or None == b`) and fixed it before running the tests.
- Docs:
  - The root README got a "Next step: Python 3.15" section. It explains which
    3.13 gaps the version works around, then gives five steps:
    1. Bump the runtime.
    2. Call `set_groups()` with a group list read from an environment
       variable.
    3. Delete `lib/openssl/` and the `OPENSSL_CONF` lines.
    4. Delete the hook, and check how 3.15 spells the group names.
    5. Run the matrix in-process.
  - `lib/README.md` explains how the group is read, and points to that
    section.
  - `cloud/README.md` documents the panel column and the API fields.

### Verification

`make check` passed with 102 tests.

The browser pane couldn't open the panel: its certificate comes from the dev
CA, and the pane also can't reach a plain-HTTP viewing proxy started from the
assistant's shell. No Chromium-based browser was installed for a headless
screenshot either. Instead, the assistant ran the real `app.js` under Node,
against a minimal fake DOM fed by the live API:

- **Cloud on hybrid-only:** only `gw-1` was listed, under "All connected
  gateways use post-quantum hybrid key exchange."
- **Default mode:** `gw-1` showed as hybrid (green) and `gw-2` as classical
  (amber), with the "1 of 2 gateways" warning.

The gateway and cloud logs matched. Nobody saw the panel rendered in a
browser during the session.

While editing `cloud/README.md`, the assistant noticed that it still
described the panel as read-only, which the earlier group-editing commits had
made outdated. Rather than widen this change, it suggested a separate
background task, which the developer started.

## 4. Pull request

When the developer chose "Create PR", the docs task was editing
`cloud/README.md` in the same checkout (no separate worktree), and might still
have been running. To keep the PR to this session's work, the assistant:

1. Created the branch `mlkem-gateway-cloud`.
2. Staged only its own three hunks of `cloud/README.md`. It built that
   version of the file from the committed one and wrote it to the index
   without touching the working tree.
3. Re-ran `make check`, then committed and pushed.
4. Opened PR #1 against `main`, ready for review.

The description covered:

- the private-API trade-off;
- Python 3.15 as the next step;
- the fallback risk;
- the certificate regeneration and database reseed;
- that the panel docs would come separately.

The repository had no CI checks at that point. The PR was merged later the
same day.

## Where the developer steered

- Required, from the start, that gateways and clouds with and without ML-KEM
  keep working together.
- Chose stable Python 3.13 with `OPENSSL_CONF` over the 3.15 release candidate
  the assistant recommended.
- Asked for each gateway's status on the dashboard, accepting the private
  CPython hook on the condition that the 3.15 replacement is clearly
  documented as the next step.
- Started the outdated-docs fix as a separate task.

## Decisions the assistant made on its own

- The `*` key-share syntax, which avoids a HelloRetryRequest with old peers.
- `config_diagnostics = 1`, the error for a missing config file, and the
  warning when `OPENSSL_CONF` is unset.
- The test design: one process per end, the group read from the ServerHello,
  and the mutation check.
- The demo details: `gateway-2`'s IP, `rd-5`'s zone and group, and keying the
  Makefile's `certs` target on `gateway-2.pem`.
- Logging the group on both ends, the panel's summary line and its amber
  colour.
- Verifying Docker runs from a scratch copy, so the developer's certificates
  and database stayed untouched.

## Open points at the end of the session

- The control panel relies on a private CPython API until Python 3.15.
- Nobody checked how 3.15 spells group names (OpenSSL writes `x25519` in
  lower case). `is_post_quantum()` ignores case either way.
- The new panel column was checked through `app.js` and the API, not in a
  browser.
