# AI usage: SCRUM-53, PQC readiness for patched hybrid traffic

A paraphrased summary of the Codex conversation used to implement SCRUM-53,
prepared on 2026-11-21. The developer supplied the ticket and the patch cutoff.
Codex inspected the repository, proposed how to apply the cutoff to recorded
traffic, implemented the change and ran static checks.

## 1. Request and existing behavior

The developer asked Codex to update local `main`, create the branch
`SCRUM-53-as-a-pqc-migration-manager-i-want-readiness-to-show-only-safe-gateways`,
and update the score in Stakeholders → PQC migration. The ticket said to count
hybrid traffic from gateways without a known vulnerable OpenSSL version and to
treat OpenSSL 3.5.7 and newer as patched for the simulated ML-KEM advisory.

Codex found that the score on `main` counted every recorded hybrid event in
the last hour. The dashboard used SCRUM-51's OpenSSL checks for live gateway
coverage and warnings, with 3.5.8 as the patch cutoff. Access events saved the
negotiated group and had no OpenSSL version fields.

## 2. Decisions and follow-up

The developer recalled the earlier SCRUM-11 decisions in the follow-up
conversation. The score measures a rolling one-hour window, gives unknown key
exchanges zero credit and uses the key exchange recorded when the event
happened. Every event in the window remains in the denominator. An empty
window still gives an unavailable score.

Codex kept those rules and applied the existing check for both ends of the
gateway-to-cloud connection to historical traffic. It chose to save the OpenSSL
versions with each event so a reconnect or upgrade cannot change the recorded
facts about earlier traffic. Events with a missing or unreadable version earn
zero credit, including older events before the version fields were added.

When the developer asked how the scores differ, Codex gave an example. If all
100 events used hybrid key exchange, the earlier score was 100%. If only 70
of them used patched OpenSSL at both ends, the updated score is 70%.

## 3. Implementation and verification

- The first implementation changed the shared cutoff in `lib/src/lib/openssl.py`
  to 3.5.7, following the ticket's original wording.
- `lib/src/lib/hub.py` and `cloud/gateways.py` capture the TLS group and OpenSSL
  versions for the connection that handled each access request.
- `cloud/schema.sql` and `cloud/db.py` store both versions and add the new
  columns to existing databases while preserving access history.
- `cloud/summary.py` credits hybrid events when both recorded versions pass
  the advisory check. `cloud/static/stakeholders.js` explains the calculation
  in the migration tab.
- Codex updated the existing test cases for the patch boundary, legacy events,
  overlapping reconnects and readiness after a disconnect. Ruff, Pylint and
  `git diff --check` passed during implementation. The test suite was not run.
- The gateway version comes from its own report, so the score depends on the
  accuracy of that report.

## 4. Review follow-up

The developer asked Codex to update PR #21 so OpenSSL 3.5.7 remains affected
and 3.5.8 is the first patched version. The readiness score should still
credit only hybrid traffic with patched OpenSSL at both ends.
