# AI usage: initial implementation

This documents the prompts and design decisions behind the first working
version of the system, written with Claude Code (model: Claude Opus 5.5). The
prompts are paraphrased. The assistant's design questions and the developer's
answers are kept in full, because they shaped the code.

The codebase has changed a lot since then (ML-KEM on the gateway → cloud hop,
an editable control panel, a second gateway, the `tests/` layout, CI/CD). This
document describes the initial version, not the current one.

## 1. Task

The developer provided the architecture diagram (`docs/dev_course.png`), the
written spec (`docs/system_spec.md`) and a description of the database
relations, with this prompt:

> Implement the system by writing code into the existing repository layout.
> Keep the system as simple as possible and review code complexity along the
> way. Don't stage, commit or push. If the layout seems odd, or you have
> another idea of how to implement something, ask me instead of making
> executive decisions, and raise all ideas. Document in each component's
> README whatever isn't already evident from the spec. Write unit and
> integration tests, and make sure the code passes `make lint`. Put shared
> code in `lib/`. Remove all references to Docker Swarm: testing and
> deployment use plain Docker.

## 2. Design questions

Before writing code, the assistant asked its questions in rounds, each with a
recommendation.

### Round 1

| Question | Decision |
|---|---|
| Every component has its own `src/` package, so `from src…` imports collide between components when tests and linters run from the repo root. How should this be resolved? | Make each component a package (`cloud/`, `gateway/`, `reader/`) with its tests in `<component>/test/`, run as `python -m <component>` |
| The spec calls the edge device "Access Reader" (`READER_ID`, `ZONE`, `GATEWAY`), but the directory is `lock/`, and the diagram says `EDGE_GATEWAY=ip:port`. Which names should be used? | Rename `lock/` → `reader/`, and use the spec's env var names |
| How should classical TLS 1.3 (reader → gateway) and TLS 1.3 + ML-KEM (gateway → cloud) be implemented? | The stdlib `ssl` module with an OpenSSL config per component (later replaced, see below) |
| The local venv's OpenSSL has no ML-KEM. How should that be handled? | Recreate the venv with Python 3.13 (`PYTHON ?= python3.13` in the Makefile) |

### Mid-round change: no ML-KEM yet

While round 1 was being answered, the developer added:

> In the initial version, don't use ML-KEM. Use regular TLS.

OpenSSL ≥ 3.5 picks the hybrid `X25519MLKEM768` by default, so plain code
would still use ML-KEM. The assistant tested that
`SSLContext.set_ecdh_curve('X25519')` restricts both client and server to
classical X25519, then asked the second round.

### Round 2

| Question | Decision |
|---|---|
| How should every hop be kept classical? | "In the second version of the codebase, ML-KEM will be implemented. Ship the shape that allows easy migration, but use non-PQC encryption on every hop for now." Implemented as one TLS helper in `lib` with a key-exchange group constant per hop |
| The venv recreation was only needed for ML-KEM. Still recreate it? | Yes, with Python 3.13 |
| How should certificates be created and trusted? | `make certs` creates a dev CA and server certificates. Clients verify the server; no client certificates |
| What should the components speak on top of TLS? | "The components should talk over WebSockets because of the 'visibility down' problem: the upper components don't know the addresses of the components below them. The clients attach to the servers with sockets and the server keeps those connections in memory. Otherwise use stdlib + HTTPS + JSON as good defaults. Don't overcomplicate." |

### Round 3

| Question | Decision |
|---|---|
| The stdlib has no WebSockets. Which library? | "Either websockets or aiohttp. The main requirement is that the code stays simple and avoids async deadlocks. Pick the simpler one." The assistant chose `websockets` |
| Many readers share the gateway's single cloud connection. How should replies be matched to requests? | Request IDs, with a receiver routing each reply back to its request |
| How should the cloud serve both the gateways and the control panel? | Two listeners: WSS for gateways, HTTPS for the panel |
| The spec doesn't mention admin authentication for the panel. Add any? | No authentication; document it as an accepted risk |

### Round 4

| Question | Decision |
|---|---|
| Which keys does a reader "scan", and how often? | `KEYS` and `SCAN_INTERVAL` env vars on the reader, with defaults |
| Where does the database live, and how does it get its data? | SQLite at `./data/cloud/master.db`. Tables are created on start, and the example data is loaded into a new database. An `ACCESS_EVENTS` table is the access log |
| How should integration tests work? | Real cloud and gateway servers in one test process, over TLS, run by `make test` |
| Which smaller defaults are approved? | Fail closed with auto-reconnect; a compose topology from the example data (four readers, `gw-1`, an internal reader VLAN with a static gateway IP, a WAN network); sqlite-web published only on localhost. Certificate generation goes in `lib/` |

## 3. Implementation

With the decisions in place, the assistant restructured the repository,
rewrote the Makefile without Swarm (`make run`/`stop`/`ps`/`logs` on docker
compose, plus `make certs`), and wrote:

- `lib`: env config, the per-hop TLS helper (TLS 1.3 with one pinned
  key-exchange group), dev certificate generation, and a shared `Hub` class
  for the server end of a WebSocket hop.
- `cloud`: schema and seed SQL, the database class (the spec's authorization
  query, plus event logging with the zone copied at scan time), the gateway
  hub, and a read-only vanilla HTML/JS control panel with a JSON API.
- `gateway`: the cloud link (one persistent connection, request IDs,
  reconnects, fails closed on timeout) and the reader hub.
- `reader`: the gateway client (reconnects on the next scan, fails closed) and
  the scan loop with an `unlock()` stub.
- Unit tests per component, an integration test, Dockerfiles, a
  `.dockerignore` and `docker-compose.yml`.

### Design change: sync to asyncio WebSockets

The first version used the threaded (sync) API of `websockets`. Under the
integration test it crashed the Python process with heap corruption inside
OpenSSL. The library reads one TLS connection in a background thread while
other threads write to it, which OpenSSL doesn't support. A stress test
confirmed this: 5 of 6 runs crashed, and with TLS 1.3 session tickets disabled
all 6 passed.

The assistant asked:

| Question | Decision |
|---|---|
| Keep the sync API with session tickets disabled (fixes the observed crash, but the unsupported cross-thread use remains), or switch to the asyncio API (all TLS I/O on one event-loop thread)? | Switch to the asyncio API |

After the rewrite, the stress test passed in all runs and the full test suite
passed 20 runs in a row. Async tests run through a small `conftest.py` hook
instead of a new pytest plugin.

### Verification

- `make lint` passes: pylint 10.00/10, ruff check and format clean. ruff needed
  `known-first-party = ['lib']`, because the `lib/` directory at the root hides
  where the package actually is (`lib/src/lib`).
- `make test`: 79 tests pass.
- `make run` brings up the compose stack (four readers, a gateway, the cloud
  and sqlite-web). Readers get decisions matching the example data. The
  containers negotiate classical X25519 even with clients that offer ML-KEM
  first. Readers can't reach the cloud directly. The control panel shows the
  connected gateway, the readers and the access history.

### Documentation

The component READMEs cover only what the spec doesn't: extra env vars,
message formats, the panel API, and how to move a hop to ML-KEM in v2. The
root README covers running the system, the repository layout, the
implementation decisions and the accepted risks.
