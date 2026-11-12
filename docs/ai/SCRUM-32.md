# AI usage: SCRUM-32, a control panel that handles many devices

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-12 that created and
implemented Jira ticket SCRUM-32, "Improve the dashboard layout for many
readers and gateways". It records what the developer asked for, what the
assistant built, how it was checked in a browser, and where the assistant was
wrong. Tool calls and code are summarised, not reproduced.

The work was merged together with SCRUM-8 as PR #5 (`scaled-stack`), one
commit per ticket.

## 1. Creating the ticket

After the scaled stack (SCRUM-8) was committed, the developer asked for a Jira
task under the "Dashboard improvements Sprint 2" epic, with a problem
statement of their own and the DoD left for the assistant to fill in.

The assistant read the panel's HTML, JavaScript and CSS to see what goes
wrong at 12 gateways and 85 readers: one flat reader list, two matrices with a
column per reader, and every table rebuilt on each 5-second refresh. It
created SCRUM-32 under the epic, assigned to the developer and in the active
sprint (checked afterwards), with this DoD:

- readers grouped by gateway, collapsible, with a count per gateway;
- a filter by gateway and by reader ID or zone, applied to the readers list
  and both reader matrices;
- matrix header row and first column kept in view while scrolling;
- a summary of connected and classical gateways and readers;
- a refresh that keeps scroll, collapsed groups, filters and typed text;
- no page-wide horizontal scrollbar at about 1440 px on the scaled stack, and
  the default stack unchanged;
- checked by hand on both stacks, and the README updated.

Stakeholder views (SCRUM-12) and reader connections (SCRUM-15) were marked
out of scope, so the ticket didn't overlap the developer's other work. The
developer then asked the assistant to start.

## 2. Implementation

Only the panel's static files changed:

- Summary tiles: gateways connected out of known, classical gateways,
  readers, keys.
- A toolbar that stays at the top of the window, with a gateway dropdown, a
  reader/zone search and a "Showing X of 85 readers" count.
- Readers grouped by gateway in collapsible blocks with the gateway's
  connection state ("not connected" in red). Above 20 readers they start
  collapsed; a search opens the groups it matches in; a group the admin opens
  or closes stays that way.
- Tables scroll inside their own box, with sticky header rows and first
  column, and a header row above the room columns naming each gateway.
- Each part of the page is redrawn only when its data changed.

Before testing, the assistant noticed that its sticky-column CSS
(`:first-child`) would also pin the first room column once the extra header
row existed, and gave the corner cell its own class.

## 3. Getting a browser to look at it

This took most of the effort:

- The built-in browser refused `https://localhost:8444` because it doesn't
  trust the project's dev CA. The assistant did not try to bypass the
  certificate check.
- Instead it wrote a throwaway preview server, outside the repository, that
  runs the panel's own request handler over plain HTTP, with a copy of the
  scaled stack's database and a stand-in gateway list with one gateway
  offline.
- The browser pane was hidden and refused to open the preview address, and
  the app's preview launcher left the server stuck in "starting".
- A headless Chromium from the Playwright cache wouldn't start inside the
  assistant's command sandbox. The assistant asked the developer to show the
  browser pane. The developer granted macOS permissions instead. Chromium
  still didn't respond inside the sandbox, so the assistant ran it outside the
  sandbox (with the developer's approval) and gave it longer to start. A small
  script then drove it over the Chrome DevTools Protocol: setting inputs,
  waiting for refreshes, and taking screenshots.

## 4. What the browser checks found

At 1440 × 900:

- Scaled data: tiles "11 of 12" gateways, 3 classical, 85 readers; 12
  collapsed groups with the offline gateway in red; page width exactly
  1440 px.
- Filters: gw-s3 narrowed both room matrices to 8 columns; searching
  "server" found 11 readers and kept text and focus through a refresh; a
  search with no match showed a message.
- A room matrix scrolled sideways kept its position, the page kept its
  scroll, and an opened group stayed open across a refresh.
- Default data: both groups open, the tables as before plus a gateway header
  row.

Fixes that came out of the screenshots:

- The gateways table sorted `gw-s10` before `gw-s2`; now natural order.
- A gateway's label over its 8 matrix columns scrolled out of view; it now
  sticks just right of the first column.

Two problems were in the assistant's own test setup, not the panel:

- One test step declared the same variable twice in the page's global scope,
  so it silently did nothing. The assistant reran it correctly.
- Clicking a membership toggle in the preview failed with `403
  cross-origin request`, because the panel's CSRF check expects an HTTPS
  origin. The assistant confirmed this from the status line, adjusted only
  the throwaway preview server, and then saw the toggle turn green, Room
  access update ("via executives, visitors"), and undo correctly.

## 5. Result

- `make test`: 194 passed; `make lint` clean; the cloud README describes the
  layout.
- Committed as the second commit on the branch, and the running scaled stack
  rebuilt so the developer could see it.
- The developer asked for the PR; the branch was already up to date with
  `main`. PR #5 was opened and later merged, and the developer marked the
  ticket done.
- A `.claude/launch.json` the assistant created for the preview attempt was
  left untracked and not committed.

## Where the developer steered

- Asked for the ticket, with the problem statement, under the right epic.
- Granted the macOS permissions that let headless Chromium run.
- Asked for both tickets in one PR, one commit each.

## Decisions the assistant made on its own

- The DoD, the scope boundaries, and putting the ticket in the active sprint.
- Collapsing groups above 20 readers, widening the page to 80rem, and
  redrawing only changed parts.
- Verifying through a plain-HTTP copy of the panel instead of bypassing the
  browser's certificate check.
