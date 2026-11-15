# AI usage: SCRUM-15, reader connections on the dashboard

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-15 that implemented Jira
ticket SCRUM-15, "Show all reader connections in the dashboard". It records
what the developer asked for, what the assistant found and asked, what the
developer decided, and what was built and verified. Tool calls and code are
summarised, not reproduced. The same session did the Python 3.15 migration
earlier (see [SCRUM-36.md](SCRUM-36.md)).

## 1. Task

The developer asked for SCRUM-15 on a branch they had already checked out
(`reader-connections`, from `main` after PR #8). The ticket:
- all reader connections should be displayed on the dashboard, possibly as a
  dropdown list from the connected gateway;
- DoD: the list of connected readers is visible.

The assistant moved the ticket to In Progress and read the gateway, cloud and
panel code. The main finding:
- **The cloud didn't know which readers were connected.** Only each
  gateway's `ReaderHub` did.
  - The gateway → cloud protocol carried scan requests only.
  - The panel's "Readers" section listed the readers registered in the
    database, not live connections.

## 2. Design

The assistant asked three questions:

| Question | Options | Decision |
|---|---|---|
| How the cloud learns the connections | The gateway pushes its list on every change and after each reconnect (recommended); the cloud polls the gateways (requests in the other direction too); infer from recent scans (activity, not connections) | **The gateway pushes its list** |
| Where on the panel | A Connection column and counts in the existing per-gateway "Readers" lists (recommended); an expandable list under "Connected gateways"; both | **In the "Readers" lists** |
| Edge cases | Connected readers missing from the database; readers connected through another gateway than the database says; live state only, with no history | **The first two.** The developer left the third unselected, and the assistant kept connections in memory only: storing past connections overlaps SCRUM-33 and SCRUM-21 (another team member's tickets) |

The assistant chose the details itself:
- **Message format.** The report goes through the existing
  `CloudLink.request()`: `{"type": "readers", "readers": [...]}`, answered
  `ok`.
  - A cloud from before this feature answers `fail`: the message has no key
    ID, so it is no access request and nothing is logged. The gateway only
    logs a warning.
  - A gateway from before never reports, and its readers show as unknown.
- **What "no readers" means.** The gateway reports an empty list at start, so
  "no reader connected" is not confused with "the gateway doesn't say".
- **Untrusted input.** Gateways aren't authenticated, so the cloud keeps only
  the known string fields of each reader, accepts at most 1,000 readers per
  list, and refuses anything malformed.

## 3. Implementation

- **`lib.hub`.** `Hub.changed()` is a hook called on the event loop when a
  client connects or disconnects. Closing a connection that a reconnect has
  already replaced is no change.
- **Gateway.**
  - `ReaderHub.changed()` hands `CloudLink.report_readers()` the ID, address,
    connected-since time and key exchange of each connected reader.
  - `CloudLink` sends the latest list from one background task: whenever it
    changes, and after every reconnect.
- **Cloud.**
  - `GatewayHub` keeps the reported list per gateway and drops it when the
    gateway disconnects.
  - `/api/gateways` gives each gateway a `readers` list, or `null` when the
    gateway hasn't reported one.
- **Panel.**
  - Each reader in the "Readers" lists gets a Connection cell; hover shows
    the address and key exchange:
    - connected since … (green);
    - connected via another gateway (amber);
    - not registered (amber, listed under the gateway it's connected to and
      left out of the matrices);
    - not connected (red);
    - unknown (grey: the gateway is offline, or doesn't report readers).
  - Each gateway group shows "n of m readers connected".
  - The top tiles show "Readers connected" (of registered) and, when there
    are any, "Unregistered readers".

## 4. Verification and fixes

- **A gap found by a test.** The new reconnect test timed out:
  - when the cloud connection dropped, requests in flight waited out the full
    5 s timeout, so the reader list wasn't re-sent promptly after a
    reconnect;
  - the assistant made `CloudLink` fail pending requests as soon as their
    connection closes, which also fails scans closed sooner, and added a test
    for it.
- **Lint.** pylint objected to `CloudLink`'s instance-attribute count. The
  assistant disabled that check for the class.
- **Tests.**
  - New tests cover:
    - the hook;
    - the gateway's reports at start and on every change;
    - sending, re-sending after a reconnect, and an older cloud refusing the
      list;
    - the cloud keeping, replacing, forgetting and validating the lists;
    - an integration test through the panel API;
    - an e2e test that every compose reader is listed under its gateway, on
      `X25519`.
  - `make lint` rated 10.00/10, 261 unit and integration tests passed (stable
    over repeated runs), and all 12 e2e tests passed.
- **Live stack (`make run`).**
  - `/api/gateways` listed rd-1 to rd-4 under gw-1 and rd-5 under gw-2.
  - The assistant then stopped `reader-4`, ran rd-2 against gateway-2, and
    ran an unregistered `rd-99` against gateway-1.
  - It loaded the real `app.js` in Node with an inert DOM, fed it the live
    API data, and printed the rows the Readers section draws. rd-2 showed
    "connected via gw-2", rd-4 "not connected" and rd-99 "not registered".
  - Removing a gateway's list, or the gateway itself, showed its readers as
    unknown.
- **Browser.** The browser pane refused the panel's dev-CA certificate, and
  the assistant didn't route around that, so nobody saw the panel rendered in
  a browser this session.

## 5. Pull request

The developer reviewed the result and asked for three things:
- this transcript;
- a pull request against `main`;
- once they had merged it after code review, the ticket moved to Done, with
  a comment linking the PR and saying it fulfils the DoD.

The assistant committed the branch `reader-connections` and opened the PR,
which went through the advisory `can-merge` CI check. The ticket stays In
Progress until the developer reports the merge.

## Where the developer steered

- Chose the push design, the "Readers" lists, and both edge cases.
- Reviewed the change, then had the assistant open the PR and close the
  ticket only after their merge.

## Decisions the assistant made on its own

- Kept connections in memory only, with no history.
- The `type: readers` message, the empty initial list, and the field and size
  limits on what the cloud accepts.
- Failing in-flight requests at once when the cloud connection drops.
- The wording and colours of the connection states, and the two new tiles.
- Starting Docker Desktop for the e2e and live checks.
