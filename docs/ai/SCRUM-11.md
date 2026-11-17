# AI usage: SCRUM-11, track PQC readiness of all devices

A paraphrased summary of the Codex conversation used to implement SCRUM-11.
Prepared on 2026-11-17 from the conversation, commit history and merged code.
The assistant used OpenAI GPT models through Codex to inspect the project,
implement the score, run checks, explain the decisions and prepare the pull
request. Prompts, tool calls and code are summarised rather than reproduced
verbatim. This record documents the earlier implementation; adding it does
not change the readiness calculation.

## 1. Task and clarification

The developer supplied the ticket, "Track PQC-readiness of all devices",
and the ticket clarification after SCRUM-12. The existing `readiness` from
`GET /api/summary` measured the share of connected gateways using hybrid
key exchange. The clarification requested a traffic-weighted score, separate gateway
coverage, a traffic-window decision, conservative treatment of unknown
encryption, a stakeholder display alongside the connection breakdown, and
tests. Uneven simulated traffic should demonstrate the difference between
the two measures.

The work was initially labelled SCRUM-13 in the conversation and branch.
The developer corrected the ticket to SCRUM-11 and requested the final branch
name `SCRUM-11-track-pqc-readiness-of-all-devices`. The developer also
repeatedly asked the assistant to keep the dashboard changes within scope.
Amber highlighting of classical rows was left to the separate SCRUM-13 work.

## 2. How the calculation evolved

The developer asked whether the proposed calculation matched the ticket requirements
and what would fit the project. The assistant explained three versions:

- The original score counted hybrid gateways divided by connected gateways.
  One hybrid and one classical gateway therefore gave 50%, regardless of traffic.
- The first traffic calculation counted last-hour access events but classified
  them using each gateway's current encryption. An upgrade could therefore
  incorrectly make earlier classical events appear PQC.
- The final calculation records the negotiated key exchange with each access
  event and uses that recorded value. Upgrades, reconnects and disconnections
  cannot reclassify earlier events.

The developer initially asked to remove the event-recording change. The
assistant reverted it, then restored it after further discussion and the
developer's renewed request to change the calculation. The commit history
includes that addition, revert and restoration.

For the final version, the developer asked for a realistic traffic-window
choice and accepted:

- A rolling one-hour window across all gateways, replacing the latest-500-events
  limit. Every access event has equal weight.
- Readiness = events confirmed to use post-quantum hybrid key exchange divided
  by all access events in that window.
- Unknown or missing recorded key exchange counts as non-PQC, to avoid
  overestimating confirmed protection.
- No events in the window produces an unavailable score (`null`).
- Gateway coverage remains a separate ratio of hybrid connected gateways to
  all connected gateways; offline gateways are excluded from that ratio.

For example, if two gateways produce 100 events each, one with 100 PQC events
and the other with 80 classical events followed by 20 PQC events, readiness
is 120 / 200 = 60%, even if both gateways now use PQC.

## 3. Implementation

- `cloud/summary.py` computes traffic readiness, `gateway_coverage`, recorded
  classical traffic share and the non-PQC share that includes unknown events.
  It retains the gateway breakdown and existing status rules.
- `cloud/schema.sql` and `cloud/db.py` add a nullable `key_exchange` field to
  access events, migrate existing databases without deleting history, and
  aggregate counts by gateway and recorded group inside UTC time bounds.
  A timestamp index supports the window query.
- `lib.hub.Hub` keeps the negotiated group in a connection-specific
  `ContextVar`. `cloud/gateways.py` passes it to authorization logging, so
  overlapping connections with the same gateway ID retain their own group.
- `cloud/panel.py` queries all events in the last hour for `/api/summary`.
- `cloud/static/stakeholders.js` displays PQC traffic readiness and gateway
  coverage separately, adds last-hour traffic shares beside the gateway
  breakdown, and explains non-PQC traffic in the security officer view.
- The cloud README explains the score, window, unknown events and API fields.
  Existing simulated sites already had uneven scan rates, so no additional
  simulator changes were included in the final SCRUM-11 diff.

## 4. Developer questions and limits explained

The developer asked where to see the score and which dashboard sections
changed. The assistant directed them to Stakeholders → PQC migration at
`https://localhost:8444/#stakeholders/migration` and explained the separate
gateway coverage and traffic values.

When the developer noticed low readiness, the assistant inspected stored
traffic and explained that older events lacked a recorded group. Those
events count as unconfirmed PQC until they leave the one-hour window. They
are not evidence that all of that traffic actually used classical encryption.
The assistant did not assign invented encryption values to old events or
shorten the window to raise the score.

The measure uses access-event counts as a proxy for traffic, not byte counts.
It covers gateway-to-cloud key exchange, not reader-to-gateway encryption
or a complete security assessment of every device. During dashboard comparison
discussion, an illustrative preview was produced; it was not a real browser
screenshot and is not recorded here as browser verification.

## 5. Verification and delivery

- Tests cover unequal traffic and gateway coverage, unknown and legacy events,
  no traffic, time-window bounds, more than 500 events, database migration,
  gateway upgrades/disconnections and overlapping reconnects.
- Integration tests exercise real classical and hybrid TLS and confirm that
  readiness retains the recorded encryption after the gateway disconnects.
- An early local Python 3.13 check used a temporary compatibility shim outside
  the repository. It was not included in the implementation. Final validation
  used native Python 3.15 TLS APIs without that shim.
- After merging the then-current main into SCRUM-11, container validation
  passed with 271 tests and one skip, plus Ruff and Pylint 10/10.
- The local virtual environment was subsequently recreated with Python 3.15.2.
  Local `make check` passed with 272 tests, Ruff and Pylint. That environment
  update created no tracked code changes.
- The developer authorised commits, pushes and a pull request. Earlier closed
  PRs were superseded by [PR #13](https://github.com/aleksilei/Dev-course-811372A-Group-2/pull/13),
  using the final SCRUM-11 branch name. Main now contains the merged work.
- The assistant drafted a Jira comment linking the PR, recording the one-hour
  and unknown-as-non-PQC choices, and leaving amber highlighting to SCRUM-13.
  The draft was returned to the developer rather than posted to Jira.

## Where the developer steered

The developer supplied the ticket requirements, corrected the ticket number and
branch name, restricted dashboard scope, requested and later reversed a revert,
asked for a realistic calculation, approved the final approach and authorised
the pull request. The explanations about multiple gateways, historical
encryption and low readiness supported those decisions.

## Decisions the assistant made on its own

The assistant proposed the one-hour event-based measure, recorded encryption
per event, unavailable score for an empty window, SQL aggregation and index,
connection-specific context, migration mechanics, UI wording and test cases.
The developer accepted the calculation choices through the discussion. These
were AI-assisted implementation choices presented for human review in PR #13.
