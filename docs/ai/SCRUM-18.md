# AI usage: SCRUM-18, encryption status of every device

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-15 that refined and
implemented Jira story SCRUM-18. It records what the developer asked for,
what the assistant found and suggested, what the developer decided, and what
was built and verified. Tool calls and code are summarised, not reproduced.
The same session built the reader connections this story relies on (see
[SCRUM-15.md](SCRUM-15.md)).

## 1. Refining the story

The developer asked the assistant to evaluate SCRUM-18 and suggest how to
refine it before anything was implemented. The story was a title only: "As
security officer I want to see encryption status of all devices", with no
description, DoD, epic or assignee.

The assistant read the related tickets (SCRUM-11, -13, -17, -21, -28, -33,
-34) and the panel code. It reported:

- **What the panel already had:**
  - each gateway's key exchange, in the Operations tab and in the security
    officer view (only for classical and unknown gateways);
  - each reader's reader → gateway key exchange, but only in a tooltip
    (SCRUM-15).
- **What was missing:**
  - one list of every device, hybrid ones included;
  - the TLS version and cipher of any connection;
  - the panel's own link.
- **What was ambiguous:** "encryption status" (key exchange, TLS version,
  cipher, certificates, or data at rest) and "all devices".

It proposed a refined description and DoD, a backend-first design, and five
questions. The developer decided:

| Question | Decision |
|---|---|
| Scope | Encryption in transit. Data at rest goes in the README's risks: the database is assumed to be sufficiently secured |
| Where the list goes | The security officer view, since it's about stakeholder interests |
| TLS version and cipher | Yes, together with the key exchange, provided by the backend. The reader → gateway link must be captured too |
| Epic and assignee | SCRUM-5, the developer |
| SCRUM-13 (amber highlighting) | Closed by the developer, so the story uses existing colours only |

The assistant then rewrote SCRUM-18's title, description, DoD and
out-of-scope list, set the epic and assignee, and checked that both had
stuck.

## 2. Implementation

The developer asked for the implementation on a new branch. The assistant
moved the story to In Progress and branched `encryption-status` from `main`.

### Working around an open PR

PR #13 (SCRUM-11, another team member's) was open and touched the same
files:
- `lib/hub.py` (`__init__` and `handle`);
- `cloud/summary.py`;
- the security officer view's headline in `stakeholders.js`.

To keep the eventual merge small, the assistant:
- put the device list in a new `cloud/devices.py` rather than in
  `summary.py`, as the DoD had suggested;
- added the new view section below what PR #13 changes;
- changed only the lines of `hub.py` it needed.

### Built

- **`lib.tls.link_details()`:** the TLS version, cipher suite and key
  exchange of a connection.
- **`Hub`:** reads these once, on the event loop, when a client connects, and
  lists them in `connected()`. Reading them later from the panel's thread
  would touch an OpenSSL connection from two threads, which the project
  avoids.
- **Gateway:** its reader reports carry the same fields, and the cloud keeps
  them. This gives the reader → gateway TLS version and cipher.
- **`cloud/devices.py`:** a pure function that lists every registered or
  connected gateway and reader with its links. A device's status is its
  weakest link:
  - `post-quantum`, `classical`, `unknown` or `offline`;
  - unregistered devices are `unknown`, with their links still shown;
  - a reader behind an offline or non-reporting gateway is `unknown`;
  - a reader its reporting gateway doesn't list is `offline`.
- **`GET /api/devices`:** serves the list, plus the panel request's own link.
- **Security officer view:**
  - counts per status for gateways and readers;
  - a table of every device with its own link and, for readers, its
    gateway's link to the cloud, using the panel's existing colours;
  - the panel's own link;
  - a new line in "Your concerns".

## 3. Verification

- **Lint.** pylint objected twice:
  - too many local variables in the first `devices()`, which was split into
    gateway and reader helpers;
  - two test unpackings, which were rewritten.

  `make lint` then rated 10.00/10.
- **Tests.**
  - Updated: the existing hub, reader-report and gateway tests, for the new
    fields.
  - New unit tests:
    - the weakest-link rule in both directions;
    - unknown and offline states;
    - unregistered devices;
    - a reader connected through another gateway;
    - the panel link;
    - `link_details()` on a real handshake.
  - New endpoint, integration and e2e tests. The e2e test checks that every
    compose device is listed with TLS 1.3 and its expected key exchange.
  - 275 unit and integration tests and 13 e2e tests passed.
- **Stopping the scaled stack.** The developer's scaled stack was running
  again and held the ports and subnet the e2e tests need. The assistant asked
  first; the developer chose to stop it and leave it off.
- **Live stack (`make run`).**
  - The assistant rendered the real `stakeholders.js` under Node with a
    minimal DOM, from the live `/api/devices`:
    - gw-1 post-quantum, gw-2 classical;
    - all five readers classical;
    - every link TLSv1.3 with `TLS_AES_256_GCM_SHA384`;
    - the panel's own link `X25519`, classical.
  - With gateway-2 and reader-4 stopped, gw-2 and rd-4 showed as offline and
    rd-5 as unknown.
- **Browser.** As before, the browser pane doesn't trust the dev CA, so
  nobody saw the view rendered in a browser this session.

## 4. Pull request

The developer asked for a pull request that links the Jira issue, and for the
story to be moved to "In review". The assistant committed the branch, opened
the PR against `main` with the link in its description, and moved SCRUM-18 on
the board.

### Rebasing onto SCRUM-11

PR #13 (SCRUM-11) merged first, and the developer started a rebase of
`encryption-status` onto the new `main`. It stopped on the two files the
assistant had predicted:
- **`lib/hub.py`:** both sides kept. PR #13's per-request key exchange
  (`request_key_exchange()`) now reads the group from the new link details.
- **`cloud/README.md`:** PR #13's rows for the migration view and
  `/api/summary` were kept, with this story's additions to the security view
  row and the `/api/gateways` and `/api/devices` rows.

The developer's scaled stack was running again and blocked the e2e tests. The
assistant asked before stopping it; the developer chose to stop it. After the
rebase, lint rated 10.00/10, 286 unit and integration tests passed (PR #13's
included), and all 13 e2e tests passed. The rebased branch was force-pushed
with a lease.

## Where the developer steered

- Asked for a review and a refined ticket before implementing.
- Made the scope, placement, field and ownership decisions, and closed
  SCRUM-13.
- Chose to stop the scaled stack for testing and leave it off.

## Decisions the assistant made on its own

- The weakest-link status rule, and treating unregistered devices as unknown
  while still showing their measured links.
- `cloud/devices.py` instead of `summary.py`, to avoid conflicts with PR #13.
- Reading the TLS details at connect time on the event loop.
- Reporting the panel's actual connection rather than a fixed description.
- Letting the views' table helper take coloured cells, and using the
  existing pass/warn/fail colours.
