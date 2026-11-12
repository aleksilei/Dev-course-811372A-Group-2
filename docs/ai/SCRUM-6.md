# AI usage: SCRUM-6, HTTP to HTTPS upgrade for the control panel

A paraphrased transcript of the part of a Claude Code session (model: Claude
Opus 5.5, in the Claude desktop app) on 2026-11-12 that implemented Jira
ticket SCRUM-6, "Automatic HTTP to HTTPS upgrades for admin dashboard". It
records what the developer asked for, what the assistant found and decided,
what was built and verified, and where the assistant was wrong. Tool calls
and code are summarised, not reproduced. The same session went on to SCRUM-8,
SCRUM-32 and SCRUM-12, each in its own file.

The work was merged as PR #4 (`panel-https-redirect`).

## 1. Jira access and ground rules

The developer first asked whether the assistant could reach the team's Jira
space "811373A-3008 G23". Through the Atlassian connector it found one site
and one project, key `SCRUM`, with the developer as project lead and read-write
access. It listed the 24 issues, all in To Do, grouped by epic, story and
assignee, and offered to cross-check the developer's tickets against the
repository.

The developer narrowed the scope: implement only the tickets assigned to them,
starting with SCRUM-6.

## 2. Task

The ticket: the dashboard web server doesn't answer requests made over plain
HTTP, so a client that types `http://` gets an empty response. DoD: client
requests to the web server are automatically upgraded to HTTPS.

The assistant read `cloud/panel.py`, `cloud/__main__.py`, the compose file and
the cloud README. The panel is a `ThreadingHTTPServer` whose listening socket
was wrapped in TLS, on port 8444 only.

## 3. Design

The ticket's wording ("clients that connect with http") meant
`http://localhost:8444` should work, so the assistant chose to serve both on
the same port rather than open a second HTTP port:

- Every new connection's first byte is peeked. A TLS connection always starts
  with a handshake record (`0x16`); anything else is treated as plain HTTP.
- TLS connections are wrapped per connection, in the request thread, instead
  of on the listening socket.
- Plain HTTP gets a `308` redirect to the same path and query on
  `https://<Host>`. `308` rather than `301` so that a POST stays a POST. A
  request without a `Host` header gets `400`, and an absolute-form request
  line (`GET http://host/path`) is handled.
- `docker-compose.yml` needed no change.

## 4. Implementation and what went wrong

- The first full test run had **2 existing tests failing** with
  `ConnectionResetError`. The new code closed the TLS socket outright, which
  resets the connection when a rejected request's body is still unread, before
  the client reads the response. The assistant switched to a half-close first
  (the same `shutdown_request()` the server uses for plain sockets), and the
  suite passed three runs in a row.
- pylint flagged the first version of the redirect handler, which overrode
  `handle_one_request()` and set attributes outside `__init__`. The assistant
  rewrote it to map every `do_<METHOD>` to one redirect method and end the
  connection with a `Connection: close` header.
- New tests: the redirect over GET, HEAD and POST with and without a query
  string, a request without `Host`, and HTTPS still working after a
  plain-HTTP request and after a connection that sends nothing.
- The cloud README documents the redirect.

## 5. Verification

- Unit and integration tests: 174 passed; `make lint` clean.
- A locally started panel, checked with curl: `http://…/api/readers` answered
  `308`, and following it returned the readers over HTTPS.
- Docker didn't respond at first (`docker info` timed out), so the assistant
  reported the Docker stack as untested. After the developer restarted Docker,
  it stopped the developer's dev stack (the e2e tests use the same ports), ran
  `make e2e` (11 passed), then rebuilt and restarted the dev stack and
  confirmed the redirect there with curl.

## 6. Pull request #4

On the developer's request the assistant committed on a new branch and opened
PR #4. Following a note in its persistent memory, it switched the active `gh`
account from the repository owner's account to the developer's everyday
account before pushing, and said so. At the developer's request it turned on
the app's Auto-fix monitoring for the PR. The developer merged the PR and
marked the ticket done.

## Where the developer steered

- Limited the work to their own tickets, one at a time.
- Restarted Docker so the e2e tests and the live check could run.
- Asked for the commit, PR and Auto-fix.

## Decisions the assistant made on its own

- Same-port detection by the first byte, instead of a second HTTP port.
- `308` instead of `301`, and `400` for a request without `Host`.
- Stopping and restarting the developer's dev stack for the e2e run.
- Pushing from the developer's everyday GitHub account.
