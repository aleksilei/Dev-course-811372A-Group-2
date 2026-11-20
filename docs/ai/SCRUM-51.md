# AI usage: SCRUM-51, highlighting vulnerable OpenSSL versions

A paraphrased transcript of the Claude Code session (model: Claude Opus 5.5,
in the Claude desktop app) on 2026-11-20 that implemented SCRUM-51. The
session made every device report its OpenSSL version and made the control
panel highlight the vulnerable ones. It records what the developer asked for,
what the assistant found and asked, what the developer decided, and what was
built and verified. Tool calls and code are summarised, not reproduced.

Jira: SCRUM-51, the only task under SCRUM-46 (Dashboard improvements
Sprint 3).

## 1. Request and what the assistant found

The developer asked the assistant to fetch SCRUM-46 from Jira and start
implementing it. The developer would make the executive decisions, and the
assistant was to ask about the technical ones. SCRUM-46 turned out to be an
epic with no description, and its one child, SCRUM-51 ("Highlight vulnerable
of OpenSSL library versions in the dashboard"), had none either. The assistant
read the related sprint 3 tickets for context:

- SCRUM-45 ("ML-KEM vulnerability response") and SCRUM-50 ("we choose to play
  along that we are affected"): the course's simulated vulnerability.
- SCRUM-40: the images run OpenSSL 3.5.7, per CI on 2026-11-17.
- SCRUM-42 and SCRUM-44: warnings to the security officer and the CIO about
  library vulnerabilities, which are stories of their own.

In the code, no device reported its OpenSSL version to the cloud. The `Hub`
already recorded each client's TLS details, and gateways already relayed
their readers' details in the reader report.

## 2. Decisions

The assistant asked, with a recommendation each time. The developer decided:

| Question | Decision |
|---|---|
| Which versions are vulnerable | everything before OpenSSL 3.5.8, so the 3.5.7 we run is affected |
| Where the vulnerable ranges live | a constant table in `lib` (range plus advisory), changed by a release |
| How devices report their version | an `OpenSSL-Version` handshake header, relayed by gateways for their readers; missing means unknown |
| Simulating other versions | an `OPENSSL_VERSION_REPORTED` override, because all images share one base image |
| Where to highlight | the Operations tab and the CIO's top risks; the security officer view is left to SCRUM-42 |
| Device status in `/api/devices` | unchanged: the vulnerability is a separate flag |
| CIO status | the developer's own answer: per the course advisor's event description, ML-KEM itself is what's affected, so a hybrid gateway on a vulnerable OpenSSL is no safer than a classical one and counts as classical |
| Demo setup | the default stack runs the real 3.5.7 everywhere ("we are affected"); in the scaled stack the odd-numbered hybrid sites report `OpenSSL 3.5.8 (simulated)` |

Asking about the simulation again was the assistant's idea. The developer's
CIO answer made the first plan (patch gateway-1, leave gateway-2 vulnerable)
pointless, because gateway-2 is classical anyway.

## 3. What was built

- `lib/openssl.py`: the header name, the override, the `VULNERABLE` table,
  parsing of version strings (LibreSSL and malformed strings stay unknown),
  and `details()`, which returns the `openssl`, `openssl_vulnerable` and
  `openssl_advisory` fields. A bad override stops a device at startup, like
  a bad `KEY_EXCHANGE`.
- Readers and gateways send the header. `Hub` lists each client's version.
  Gateways pass their readers' versions on in the reader report, whose fields
  now live in one place (`lib.hub.REPORTED_FIELDS`).
- `/api/gateways` and `/api/devices` rows carry the three fields. The cloud
  drops reports that aren't strings or are over 64 characters.
- `/api/summary`: a "weakened" gateway is hybrid but on a vulnerable OpenSSL.
  It isn't counted as hybrid (so not in coverage, nor in the CIO's
  "protected" gateways), it counts like a classical gateway for the status,
  and it gets its own risk after the classical one. Switching to
  `hybrid-only` would not cut it off.
- Operations tab: an OpenSSL column for gateways and readers (amber and
  `: vulnerable` with the advisory as a tooltip), a "Vulnerable OpenSSL" tile,
  and a line above the gateways about weakened gateways.
- The assistant also added the weakened gateways to the migration view's
  blockers, which the developer had not asked for, because otherwise that
  view would show the lower coverage with "nothing blocking". It added one
  line to the CIO's "Addressed" concerns.
- READMEs (root, `lib`, `cloud`, `gateway`, `reader`), and unit tests in
  Python and JavaScript, plus an e2e check.

## 4. Verification and limits

- Lint (Pylint, Ruff check and format) passes, all 339 pytest tests pass
  (unit and integration), and the 20 JavaScript tests pass.
- `make run`: every container reported `OpenSSL 3.5.7 9 Jun 2026` and was
  flagged. gw-1 counted as weakened, and the CIO status went red, because
  both gateways are now exposed (one classical, one weakened).
- The browser pane does not trust the dev CA, so the assistant didn't
  screenshot the panel. The rendering is covered by the JavaScript tests.
- Not covered: the cloud's own OpenSSL, which ends every gateway link;
  traffic readiness, because events record only the key exchange; and gateways
  that don't report a version, which are not taken as weakened.

## 5. Technical-debt review and follow-up

The developer asked the assistant to assess the change's technical debt. The
assistant listed, most serious first:

1. Every advisory weakened hybrid gateways, even one unrelated to ML-KEM.
2. The fix version was written out by hand in seven places.
3. The cloud's own OpenSSL, which ends every gateway link, was ignored.
4. The views disagreed: the security officer's device list showed a gateway
   as post-quantum while the CIO view counted it as classical, and traffic
   readiness can't tell.
5. A missing version counted as safe.

There were also smaller shortcuts: version strings miss Debian's backported
fixes, versions are self-reported, and the clients read the env variable in
their constructors.

The developer decided:

- **3 belongs in this ticket.** The cloud checks its own version too, and the
  same `OPENSSL_VERSION_REPORTED` override can make it report 3.5.8.
- **5: a missing version is assumed vulnerable.** An old gateway that was
  never restarted onto a patch most likely runs an old version. The assistant
  asked whether versions the cloud can't check (LibreSSL, malformed) should be
  treated the same, and the developer agreed.
- **4 goes to SCRUM-42**, refined to cover updating the security officer view.
- On the assistant's questions: the cloud's version shows on the Operations
  tab and in the API; only the scaled stack's cloud reports a simulated 3.5.8,
  so the default stack stays fully affected; and items 1 and 2 are fixed too.

What changed:

- `lib/openssl.py`: `Advisory` rows with an `affects` field (`ML_KEM`), with
  texts and `fixed_in()` built from the table. A connected device whose
  version is missing or can't be checked is assumed vulnerable to every
  advisory (`openssl_checked: false`); a device that isn't connected claims
  nothing (`UNKNOWN`). `weakens_hybrid()` is the one rule for both ends of a
  link.
- The cloud checks its own version (`GatewayHub.openssl_version`).
  `/api/gateways` rows have `weakened`, and `/api/devices` and `/api/summary`
  have `cloud`. When the cloud is the cause, the CIO risk reads "The cloud
  runs a vulnerable OpenSSL".
- The scaled stack's cloud reports `OpenSSL 3.5.8 (simulated)`.
- Operations tab: "not reported" or "can't check: assumed vulnerable" labels,
  a line for the cloud's own OpenSSL, and the cloud counted in the tile.
- `summarize()` now takes its optional arguments by keyword only, and carries
  a Pylint disable for its argument and local counts, because it is a pure
  function of everything the cloud knows.

Validation: Pylint 10/10, Ruff check and format, 358 pytest tests and 21
JavaScript tests passed. The first e2e run couldn't start: a scaled stack the
developer had running held the `10.10.0.0/24` network. After the developer
stopped it, all 14 e2e tests passed. They include the check that every device
and the cloud report the image's OpenSSL, and that gw-1 counts as weakened.

With the developer's approval of the drafted text, the assistant added a
description to SCRUM-42 (the summary unchanged). It now covers updating the
security officer view to show weakened gateways and each device's, and the
cloud's, OpenSSL version.
