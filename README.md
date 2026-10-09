# Dev-course-811372A-Group-2

Simulated NFC door access system: **Access Readers** ask an **Edge Gateway**,
which relays to the **Cloud Server**, whether a key may pass. The spec and
architecture diagram are in [`docs/`](docs/system_spec.md).

```
reader-1..4 --WSS--> gateway-1 --WSS, X25519MLKEM768--> cloud  <--HTTPS-- admin (control panel)
reader-5    --WSS--> gateway-2 --WSS, X25519 (legacy)-->        sqlite-web on 127.0.0.1:8080
   (reader-vlan, internal)        (wan)
```

## Setup for local development

Requires Python 3.13 (override with `make venv PYTHON=...`) and the OpenSSL 3
command line tool (`openssl version` should report 3.x) for certificates.

Create the python virtual environment
```bash
make venv
```

Install dependencies
```bash
make install
```

## Running the system

Start everything with docker compose. This also creates the dev certificates
in `data/certs/` the first time:
```bash
make run
```

- Control panel: https://localhost:8444 (trust `data/certs/ca.pem` or accept
  the browser warning). It shows each connected gateway's key exchange, and
  flags the classical ones.
- Database editor (sqlite-web): http://127.0.0.1:8080
- Follow the readers deciding: `make logs SERVICE=reader-3`
- `gateway-2` stands in for a gateway without ML-KEM (classical `X25519`
  only), with `reader-5` behind it. The cloud falls back to `X25519` for it;
  uncomment the `hybrid-only.cnf` line in `docker-compose.yml` to see it
  refused (and `reader-5` failing closed).
- Stop: `make stop`

All state lives in `data/` (gitignored): `data/certs/` and the SQLite database
`data/cloud/master.db`, which is seeded with the example data on first start.
A database from before `gw-2`/`rd-5` were added doesn't know `rd-5`, so its
scans fail until you delete `data/cloud/master.db` (or add the rows in
sqlite-web).

## Repository layout

| Path | |
|---|---|
| `reader/`, `gateway/`, `cloud/` | one package + Dockerfile + README per component, run as `python -m <component>` |
| `lib/` | shared code: env config, TLS contexts, WebSocket hub, certificates |
| `tests/unit/<component>/` | unit tests, one directory per component |
| `tests/integration/` | integration tests: readers → gateway → cloud in one process, over real TLS |
| `tests/e2e/` | end-to-end tests: the docker-compose deployment, from the built images |
| `.github/workflows/` | [CI/CD](#cicd): checks on every pull request, image releases on `v*` tags |

## Implementation decisions

- **WebSockets on both hops.** The upper components don't know the addresses of
  the ones below, so clients connect upwards and servers keep the connections
  in memory (`lib.hub`). All WebSocket code uses the asyncio API of the
  `websockets` package.
- **Post-quantum hybrid key exchange on the gateway → cloud hop.** TLS 1.3
  with `X25519MLKEM768`, falling back to classical `X25519` when the other end
  has no ML-KEM, so upgraded and older gateways and clouds work together. Set
  through an OpenSSL config (`OPENSSL_CONF`), because Python 3.13 can't set it
  per connection; nothing above `lib.tls` changes. The reader and admin hops
  stay on classical `X25519`. See [lib/README.md](lib/README.md#gateway--cloud-ml-kem-hybrid-with-classical-fallback).
- **The control panel shows the key exchange of each gateway**, read from the
  TLS handshake through a CPython debug hook until the
  [move to Python 3.15](#next-step-python-315) brings a public API for it.
- **Fail closed.** Any timeout, disconnect or malformed answer means no access.
- Env vars beyond the spec (ports, certificate paths, `KEYS`, `SCAN_INTERVAL`,
  `DB_PATH`) all have defaults; see each component's README.

## Acknowledged risks (out of scope)

- The cloud does not authenticate gateways (no mutual TLS), and gateways don't
  authenticate readers.
- The reader → gateway hop has no post-quantum key exchange (per the spec).
- Gateway → cloud connections that fall back to classical `X25519` (an end
  without ML-KEM) can be recorded now and decrypted by a future quantum
  computer, until the cloud is switched to `hybrid-only.cnf`. The control
  panel lists which gateways those are.
- Certificates are classical (ECDSA P-256) on every hop.
- The control panel has no admin authentication.
- Physical access to the reader VLAN is assumed to be safe.
- No gateway or cloud response caching for redundancy: the cloud being down
  means every door stays closed.

## Next step: Python 3.15

The ML-KEM version works around two things Python 3.13's `ssl` module can't
do, both added in Python 3.15: setting the key-exchange groups of a context
(`SSLContext.set_groups()`) and reporting the group a connection negotiated
(`SSLObject.group()`). The workarounds are the process-wide OpenSSL configs in
`lib/openssl/`, and a private CPython debug hook (`SSLContext._msg_callback`)
that reads the group out of each ServerHello for the control panel and logs.
Moving to 3.15 replaces both with public APIs. Nothing changes on the wire, so
3.13 and 3.15 gateways and clouds work together during the rollout.

Do it once `python:3.15-slim` is a final release (Docker Hub only had
`3.15-rc-slim` in October 2026):

1. **Runtime:** `FROM python:3.15-slim` in the three Dockerfiles,
   `PYTHON ?= python3.15` in the `Makefile` and `requires-python = ">=3.15"`
   in `lib/pyproject.toml`. Check that the pinned pylint and astroid support
   3.15.
2. **Groups per context:** `lib.tls._restrict()` calls
   `context.set_groups(group)` instead of `set_ecdh_curve()`, and
   `GATEWAY_CLOUD` becomes a group list read from an environment variable:
   `*X25519MLKEM768:*X25519` (hybrid with fallback, the default),
   `X25519MLKEM768` (hybrid only) or `X25519` (classical).
3. **Remove the OpenSSL configs:** delete `lib/openssl/`,
   `_check_openssl_conf()` and the `OPENSSL_CONF` lines in the gateway and
   cloud Dockerfiles. In `docker-compose.yml`, `gateway-2` and the commented
   hybrid-only switch of the cloud use the new environment variable.
4. **Remove the debug hook:** delete `_record_group()`, `_server_hello_group()`
   and `_negotiated` from `lib.tls`. `negotiated_group()` already uses
   `SSLObject.group()` when it exists, so the control panel and the logs keep
   working. Check how 3.15 spells the group names (OpenSSL writes `x25519` in
   lower case); `is_post_quantum()` ignores case.
5. **Tests:** with groups per context, the key-exchange matrix in
   `tests/unit/lib/test_tls.py` no longer needs a process per peer, so
   `tests/unit/lib/tls_peer.py` goes away and the matrix runs in-process.
   The `_server_hello_group()` tests go with the debug hook.

## Useful commands

There are quite many other useful make targets that can be checked with:
```bash
make help
```

### Tests / Linters

Run all checks **(Do this before committing)**
```bash
make check
```

Run pytests with
```bash
make test
```

It runs `tests/unit` and `tests/integration` (the `testpaths` in
`pyproject.toml`, so a plain `pytest` does the same). `async def` tests run
through a small hook in `tests/conftest.py`, with no pytest plugin needed.

Run the end-to-end tests. They build the images, start the compose stack from
them and check it from outside, as the doors and an admin see it: decisions,
the key exchange of every hop, panel edits, the cloud going down, the cloud
switched to hybrid-only. The stack gets its own certificates and database, so
`data/` is left alone, but it uses the same ports as `make run`: stop the dev
stack first.
```bash
make e2e
```

You can run pylint and ruff with
```bash
make lint
```

or with the fix parameter for ruff (automagically fixes some issues)
```bash
make fix
```

## CI/CD

GitHub Actions, in `.github/workflows/`:

| Workflow | Runs on | |
|---|---|---|
| `pr.yml` | every pull request | `make lint` and `make test`, `make e2e`, and `can-merge`, which passes when both do |
| `release.yml` | a `v*` tag | the same checks, then builds the images for amd64 and arm64, runs the e2e tests on the amd64 ones and pushes them to the GitHub container registry |
| `test.yml` | called by both | lint and tests, in `python:3.13-slim`: its OpenSSL has ML-KEM, and the runner's doesn't (pytest would skip those tests) |

**Merging.** A pull request may be merged once its `can-merge` check is green.
GitHub doesn't enforce that here (a private repository on GitHub Free has no
branch protection), so don't merge a red one. With GitHub Pro or a public
repository, protect `main` and require `can-merge` alone.

**Releasing.** After a `git fetch`, tag a commit on `main` with `v` and a SemVer
version, and push the tag:
```bash
git tag v1.0.0 origin/main
```
```bash
git push origin v1.0.0
```

A tag that isn't `v<SemVer>` (e.g. `v1.0.0`, `v1.1.0-rc.1`) or isn't on `main`
fails before anything is built. The images are built once into a temporary
registry, the e2e tests run on them, and only then are those same images (same
digests) copied to `ghcr.io/aleksilei/dev-course-811372a-group-2/` as `cloud`,
`gateway` and `reader`, tagged `1.0.0`, plus `1.0` and `latest` when it is the
newest release (a pre-release gets only its own tag).

The packages are private, like the repository. To pull one, log in with a
personal access token (classic) that has the `read:packages` scope:
```bash
docker login ghcr.io -u <your GitHub user>
```
```bash
docker pull ghcr.io/aleksilei/dev-course-811372a-group-2/cloud:1.0.0
```
