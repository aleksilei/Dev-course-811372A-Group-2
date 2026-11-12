# AI usage: SCRUM-12, stakeholder views

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-12 that planned and
implemented Jira ticket SCRUM-12, "Stakeholder view selector", and the Jira
work around it. It records what the developer asked for, what the assistant
proposed and asked, what the developer decided, and what was built and
verified, including where the assistant was wrong. Tool calls and code are
summarised, not reproduced.

The work was merged as PR #6 (`stakeholder-views`).

## 1. Input: the persona cards

The developer shared the course's persona cards (a two-page PDF) and a slide
with a message from Emma, the CIO. The assistant confirmed it could read the
PDF and summarised it:

| Persona | Question | Asks for | Position on classical fallback |
|---|---|---|---|
| Sarah, security officer | Which connections are still quantum-vulnerable? | detail, not a score; no "green" while harvest-now-decrypt-later exposure remains | turn it off this quarter |
| Michael, PQC migration PM | How close are we, what's blocking us? | one readiness score to report upwards | keep it for legacy devices until 2028 |
| Emma, CIO | Do I need to worry? | green/amber/red and the top three risks | no outages, no extra budget, meet the key customer's deadline |

The slide, which is not in the PDF, said the dashboard must from now on first
and foremost help show the largest customer where the company stands, and
asked the team for a Sprint 2 plan.

## 2. Planning

The developer called the ticket "SCRUM-5 Stakeholder view selector"; the
assistant pointed out that SCRUM-5 is its epic and the ticket is SCRUM-12.
It read SCRUM-12 and the related tickets (SCRUM-11 readiness score and
SCRUM-13 amber highlighting, both Dorsa's; the persona stories SCRUM-17, 18,
21 and 28) and noted that SCRUM-12's DoD asks each view to say which concerns
are addressed, not yet addressed, or won't be.

It proposed a view per persona, a possible fourth "customer" view for Emma's
directive, an `/api/summary` endpoint in Python so the rules are unit-tested,
and asked four questions:

| Question | Decision |
|---|---|
| A separate customer view, or fold it into Emma's | **Fold into Emma's view** |
| Readiness: share of gateways on hybrid, or weighted by readers or traffic | **Share of gateways on hybrid** |
| Build the score here and tell Dorsa, or leave her a placeholder | **Build `/api/summary` and the selector here, tell Dorsa; no placeholder** |
| Status rules: green all connected and hybrid; red a gateway offline or over half classical; amber otherwise | **Accepted** |

The developer also asked for the views to be their own tab, and for two
subtasks under SCRUM-21 for Dorsa: storing access requests in the database,
and a Logs tab. The assistant pointed out that access requests were already
stored (`ACCESS_EVENTS`, shown as "Access history") while connections were
not, and asked:

| Question | Decision |
|---|---|
| First subtask: store gateway connections, or access requests as written | **Store connections** (also what enables downgrade detection later) |
| Logs tab: connections and access history, or connections only | **Both**, with Access history moving there |

It created SCRUM-33 (store gateway connections) and SCRUM-34 (Logs tab),
assigned to Dorsa, then drafted SCRUM-12's DoD and the tab layout
(Operations, Stakeholders, and later Dorsa's Logs). The developer approved;
the assistant wrote the DoD into SCRUM-12 and, as the developer said every PR
was merged, branched from an up-to-date `main`.

## 3. Implementation

- `cloud/summary.py`: a pure function behind `GET /api/summary`, using the
  connected gateways, the gateways and readers in the database and the newest
  500 access events. It returns readiness, gateway counts, the classical,
  unknown and offline gateways with reader counts and traffic share, what
  switching to hybrid-only would disconnect, the status and plain-language
  risks. `Database.gateway_ids()` was added for it.
- Panel: "Operations" and "Stakeholders" tabs, kept in the URL
  (`#stakeholders/cio`). `stakeholders.js` draws three views:
  - CIO (default): status, "8 of 11 connected site gateways protected…", top
    three risks, no addresses or device names, so it can be shown to the
    customer;
  - PQC migration: the score as one number with a progress bar, and the
    gateways blocking it with a next step;
  - Security officer: an "Exposed: N connections" badge that is never green
    while a classical connection remains, share of traffic over classical, the
    vulnerable connections, the hybrid-only cost, offline gateways.

  Each view ends with "Your concerns": addressed, not yet addressed, and won't
  be addressed here. The fallback-deadline conflict between Sarah and Michael
  is recorded as a policy decision the dashboard shows but doesn't make.
- 14 new tests, covering the status rules (including exactly half classical),
  offline and unknown gateways, the endpoint on seed data and gateway order.
- The cloud README documents the tabs, views, rules and endpoint, and notes
  that the views are presentation, not access control: the panel has no
  authentication, so the CIO view is for showing a customer, not for exposing
  the panel to one.

## 4. Verification and fixes

- `make test`: 208 passed; `make lint` clean.
- Headless Chromium (set up during SCRUM-32) at 1440 px against the panel
  handler: on scaled data with one gateway offline, all three views rendered
  and switched, the selected view survived a refresh, the Operations tab
  still worked, and nothing scrolled the page sideways. On default data the
  CIO view said "Needs attention" with the two expected risks.
- Fixes from what it saw:
  - the summary listed `gw-s10` before `gw-s9`; gateways are now sorted
    naturally, with a test;
  - the red status text ("…or most still use…") was misleading when red came
    only from an offline gateway; it now points to the risks;
  - "1 of 2 gateways use" became "uses".
- The rebuilt scaled stack reported amber with readiness 0.75 (9 of 12
  gateways hybrid).

The developer used the app's create-PR command; the assistant committed and
opened PR #6, which the developer merged.

## 5. Jira follow-up

- **SCRUM-11 (Dorsa).** The assistant first drafted a note saying the score
  now lives in `/api/summary`. The developer pointed out that what is wanted
  from Dorsa is a proper score weighted by non-PQC traffic, while the current
  number is gateway coverage. The assistant agreed: it measures exposure
  rather than progress, and `classical_traffic_share` is already computed. It
  added points for her DoD:
  - rename the current field so the two numbers aren't confused;
  - a time window instead of "last 500 events";
  - count unknown key exchange as non-PQC;
  - offline gateways stay ambiguous until SCRUM-33;
  - the simulation's uniform traffic hides the difference;
  - keep the details next to the score, for Sarah.

  The developer approved the revised comment, and the assistant posted it
  without an @-mention, leaving the DoD to Dorsa.
- **Closing comments.** At the developer's request the assistant posted
  "PR #N has been merged which fulfills the DoD", with the PR linked, on
  SCRUM-6 (#4), SCRUM-8 and SCRUM-32 (#5) and SCRUM-12 (#6). It checked that
  all three PRs were merged first.
- **SCRUM-35.** The developer asked for a backend ticket for themselves:
  readers scanning at random intervals within a range. The assistant created
  it under "Backend improvements sprint 2", in the active sprint. Its DoD
  includes keeping `SCAN_INTERVAL` as a fixed interval so the e2e tests keep
  working, and giving the scaled stack's sites different ranges.

## Where the developer steered

- Folded the customer view into the CIO view and kept readiness simple for
  this ticket.
- Put the views in their own tab and split the history work into subtasks
  for Dorsa.
- Corrected the SCRUM-11 note: the real readiness score should be weighted by
  non-PQC traffic.
- Asked for the closing comments and the random-interval ticket.

## Decisions the assistant made on its own

- Flagging that access requests were already stored before creating the
  subtask.
- The three views' content, the "Your concerns" texts, the CIO view as the
  default, the 500-event traffic window and the risk wording.
- Leaving amber highlighting in the stakeholder view to SCRUM-13.

## Open points at the end of the session

- SCRUM-11: the traffic-weighted readiness score (Dorsa).
- SCRUM-13: amber highlighting of classical rows in the security officer's
  view (Dorsa).
- SCRUM-33 and SCRUM-34: connection history and the Logs tab (Dorsa), which
  unlock downgrade alerts and progress over time.
- SCRUM-35: random scan intervals (the developer).
