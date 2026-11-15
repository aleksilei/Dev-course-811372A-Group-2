# AI usage: SCRUM-39, unit tests for the panel's JavaScript

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-15 that implemented SCRUM-39,
the second ticket of the "Technical debt Sprint 2" epic (SCRUM-37). Tool calls
and code are summarised, not reproduced. The ticket came out of the same
debt review as [SCRUM-38](SCRUM-38.md).

## 1. Task

After SCRUM-38 was merged (PR #15), the developer had the assistant close it
in Jira and start SCRUM-39. The DoD:
- test each pure function of `app.js` and `stakeholders.js` with Node's
  built-in test runner, without npm packages;
- run the tests from `make test` and from CI;
- leave the scripts working unchanged in the browser.

## 2. Design

The assistant listed every top-level function of the two scripts. Twelve are
pure (they don't touch the page):
- `app.js`: `byId`, `keyExchangeLabel`, `connectionLabel`, `readerRows`,
  `groupsBy` and `redraw`;
- `stakeholders.js`: `percent`, `plural`, `linkText`, `statusCounts`,
  `route` (reads only the URL hash) and the `DEVICE_STATUS` colour map.

Every other function builds the page or calls the API.

The scripts aren't modules, and they start the panel as soon as they load.
Rather than add exports or startup guards to them, the assistant loads them
as they are:
- `tests/unit/cloud/static/panel.mjs` runs both scripts, in `index.html`'s
  order, inside a Node `vm` context.
- That context has a stand-in page and a `fetch` that never answers.
- Tests pick the scripts' functions and constants by name.

Values from the context use that context's `Object` and `Array`, which
`assert.deepStrictEqual` treats as different from the test's own, so the
tests compare plain JSON copies.

This came out of the throwaway Node scripts the assistant had used to check
SCRUM-15, SCRUM-18 and SCRUM-38, which nothing kept running.

## 3. Implementation

- **Tests.** `app.test.mjs` and `stakeholders.test.mjs`, 17 tests:
  - natural ID order;
  - the gateway key-exchange label;
  - every connection-label case: same gateway, another gateway, an
    unregistered reader or gateway, missing details, not connected, offline,
    unknown;
  - reader rows, with their grouping and sorting;
  - group membership lookups;
  - `redraw` skipping unchanged data;
  - percentages, plurals and link texts;
  - status counts and the status colours;
  - URL routing, including unknown tabs and views.
- **`make test`** runs pytest, then `node --test` on the test files. It
  stops with a clear message if Node.js is missing.
- **CI** (`test.yml`) installs Debian's `nodejs` next to `make` in the
  `python:3.15-slim` container.
- **README:** Node.js 20 or newer as a requirement, the test layout, and
  what the CI image installs.

The scripts in `cloud/static/` aren't changed.

## 4. Verification

- All 17 tests passed on the developer's Node.js v26.12.1.
- **Mutation check.** The assistant made `connectionLabel()` colour every
  connection green, which failed 3 tests, then restored the file.
- **CI image.** In `python:3.15-slim` with Debian's Node.js v20.19.2, all 17
  passed. A first attempt seemed to show no results, but only because Node 20
  reports in TAP format, which the assistant's `grep` didn't match.
- **Full check.** `make test` ran pytest and the JavaScript tests together.

## 5. Pull request

The developer chose "Create PR". The assistant committed the branch and
opened a ready-for-review PR against `main`, linking SCRUM-39.

## Decisions the assistant made on its own

- Loading the unchanged scripts into a `vm` context instead of adding
  exports, so the browser runs exactly what it ran before.
- Testing `route()` through the stand-in URL hash, and the status colour
  map as a constant.
- Not testing functions that build the page or call the API, as the DoD
  scopes it.
