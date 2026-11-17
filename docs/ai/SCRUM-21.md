# AI usage: SCRUM-21, current and past gateway connections

A paraphrased summary of the Codex conversation used to implement SCRUM-21
and its subtasks, SCRUM-33 and SCRUM-34. Prepared on 2026-11-17 from the
conversation and repository history. The assistant used OpenAI GPT models
through Codex to inspect the code, implement changes, run checks, resolve
merge conflicts and prepare the pull request. Prompts, tool calls and code
are summarised rather than reproduced verbatim.

## 1. Developer request and scope

The developer asked the assistant to create
`SCRUM-21-as-security-officer-i-want-to-see-all-current-and-past-connections`
from updated `main` and implement both subtasks in that branch.

The security officer needed gateway-to-cloud connection records showing who
connected, when, and with which key exchange. Comparing a gateway's earlier
hybrid connections with later classical ones should make a possible
downgrade visible. The developer supplied these requirements:

- SCRUM-33: persist each connection, close it on disconnect, handle records
  left open after a cloud restart, provide a gateway-filtered history API,
  add unit tests and document the database and endpoint.
- SCRUM-34: add a Logs tab beside the existing tabs, display gateway history
  with classical key exchange in amber, support a gateway filter, move
  Access history there with its key and reader filters, and update the README.
- Keep current connections live as in SCRUM-15 and SCRUM-18.
- Automatic downgrade alerts and reader-to-gateway history are outside scope.

## 2. Inspection and implementation

The assistant inspected the database, gateway hub, panel API, dashboard and
existing tests. The shared hub already measured the connection address and
negotiated key exchange, but retained connections only in memory.

For SCRUM-33, the assistant added:

- `GATEWAY_CONNECTIONS` in `cloud/schema.sql`, storing a session ID, gateway
  ID, address, key-exchange group, PQC status and UTC connect/disconnect times.
- Database methods to create and close a session, list history newest first,
  filter by gateway and close records left open by an earlier cloud process.
- Asynchronous lifecycle hooks in `lib.hub.Hub`, implemented by
  `cloud.gateways.GatewayHub`. SQLite writes run through `asyncio.to_thread`.
  Each physical connection gets its own record, so overlapping reconnects
  with the same gateway ID can close independently.
- Startup cleanup before serving connections. Leftover sessions receive the
  startup time as their disconnect time; this is a recovery timestamp, not
  a measurement of the exact moment a previous process stopped.
- `GET /api/connections?gateway=`. Omitting the gateway includes sessions
  from any gateway. The review follow-up below caps each response at the
  newest 100 matching sessions. Unknown key exchange and PQC status remain null.

For SCRUM-34, the assistant added:

- A Logs tab at `#logs`, with connection history and a gateway dropdown.
- Gateway, address, key exchange, PQC status and both timestamps in the log.
  Classical key-exchange cells use the existing amber styling. An empty
  disconnect time identifies an open session.
- Access history in the Logs tab, retaining its existing key and reader filters.
- Updated dashboard routing, stakeholder concern text and cloud README.

The Operations tab continues to display live connections. Connection history
is fetched while Logs is selected and refreshed with the existing polling.

## 3. Developer follow-up and pull request

The developer asked for a simple explanation of each task, where to find
Logs, how filtering works and whether live connections were preserved.
The assistant explained the gateway dropdown and the corresponding API:
`/api/connections?gateway=gw-1`.

At the developer's request, the assistant committed and pushed the work as
`dcff7be` and opened PR #17.
It also drafted a Jira comment linking the PR and describing both subtasks;
the draft was returned to the developer, not posted to Jira.

## 4. Updating from main

The developer then asked to update the branch with `main`. The assistant
fetched and merged `origin/main`, which now included SCRUM-11 readiness,
SCRUM-18 device encryption status, SCRUM-38 reader state and SCRUM-39
JavaScript tests.

Conflicts in the README, database, schema, dashboard scripts, shared hub and
database tests were resolved by retaining both sets of functionality. The
dashboard refresh now uses main's device API alongside the connection log;
the hub retains main's TLS details and per-request encryption context alongside
the new session persistence. The assistant updated the TLS test fixture and
extended the JavaScript routing test to cover `#logs`.

The merge was committed as `c9a0445`, pushed to the same PR, and the PR's
validation description was updated.

## 5. Verification and limits

- Before the main merge, `make check` passed with 267 Python unit/integration
  tests, Pylint 10/10, Ruff checks and formatting on Python 3.15.2. Initial
  lint and formatting findings were corrected before that successful run.
- Tests added for this ticket cover saved session details, gateway filtering,
  unknown encryption, startup cleanup, disconnects, overlapping reconnects
  and the history endpoint.
- After the merge, all 293 Python tests and linters passed. `make check`
  then stopped because Node.js was not installed locally. The assistant ran
  the JavaScript suite separately in a temporary Node 20 Docker container;
  all 17 tests passed, including the added Logs routing case.
- No browser rendering check or Docker end-to-end suite was run for this
  ticket. The JavaScript tests exercise functions with a stand-in page;
  they do not establish that every dashboard interaction was browser-tested.

## Where the developer steered

The developer specified the branch, required both subtasks together, defined
the scope, asked for explanations of the interface, authorised the PR and
requested the main merge and this AI usage record.

## Decisions the assistant made on its own

The assistant chose the table and endpoint names, per-session integer IDs,
shared hub lifecycle hooks, threaded database writes, nullable unknown PQC
status, startup cleanup, gateway dropdown and reuse of the existing amber
styling. It selected the tests and resolved the merge conflicts. These are
AI-assisted implementation choices for human review through PR #17.

## Review follow-up: bound history queries

The developer supplied a review comment asking for `LIMIT :limit` on the
connection-history query, like access events, to avoid returning an unbounded
number of rows as the history grows. The assistant added a default limit of
100 to `Database.gateway_connections()`, applied after gateway filtering and
newest-first ordering. The panel endpoint uses that default; existing records
remain stored. Database and endpoint regression tests cover the cap, ordering
and filtering, and the cloud README describes the bounded response.

Validation after the change: all 295 Python unit/integration tests passed,
with Pylint 10/10 and Ruff checks and formatting passing.
The JavaScript suite was not rerun for this backend and documentation change;
the earlier 17-test result belongs to the main-merge validation above.

The assistant committed and pushed the fix as `8dbbfa5` to the existing
SCRUM-21 branch. The developer then requested an updated AI usage transcript
without reviewer names, and the assistant clarified the history response
limit and recorded the review request, implementation and validation here.
