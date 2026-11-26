# AI usage: SCRUM-42, OpenSSL versions in the security officer view

A paraphrased summary of the Claude Code conversation used to implement
SCRUM-42, prepared on 2026-11-24. The developer supplied the ticket. The
assistant (Anthropic's Claude Opus 5.5) inspected the code, implemented the
change and ran checks.

## 1. Request

Since SCRUM-51, a hybrid gateway with a vulnerable OpenSSL counts as
classical in the CIO and migration views, but the security officer view
still showed it as post-quantum. The ticket asked for weakened gateways in
the headline and "Quantum-vulnerable connections" with the OpenSSL version as
the reason, each device's and the cloud's OpenSSL version in the device list,
and updated concerns.

## 2. Implementation

A first version also changed the backend. The developer limited the work to
the security officer view, so the backend was reverted and the change was
made in `cloud/static/stakeholders.js` only, from data the APIs already
return:

- weakened gateways count as quantum-vulnerable, with the OpenSSL version as
  the reason;
- a list of the OpenSSL versions in use and who runs them;
- an OpenSSL column and the cloud's version in the device list;
- updated concerns, with 3.5.7 as the old vulnerable version and 3.5.9 as the
  updated one;
- tables keep their scroll position when the view refreshes.

The CIO and migration views are unchanged.

## 3. Verification

Lint and the Python tests passed. The new Node tests were not run, as Node.js
was not installed. The page was checked in a browser with data from the
running stack.
