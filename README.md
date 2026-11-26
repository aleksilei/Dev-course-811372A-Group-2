# Dev-course-811372A-Group-2

Simulated NFC door access system: **Access Readers** ask an **Edge Gateway**,
which relays to the **Cloud Server**, whether a key may pass. The spec is in
[docs/system_spec.md](docs/system_spec.md) and the architecture diagram in
[docs/dev_course.png](docs/dev_course.png). How AI assistants were used to
build it is recorded in [docs/ai/](docs/ai/).

```
reader-1..4 --WSS--> gateway-1 --WSS, X25519MLKEM768--> cloud  <--HTTPS-- admin (control panel)
reader-5    --WSS--> gateway-2 --WSS, X25519 (legacy)-->        sqlite-web on 127.0.0.1:8080
   (reader-vlan, internal)        (wan)
```

## Setup for local development

Requires:
- Python 3.15 (override with `make install PYTHON=...`)
- the OpenSSL 3 command line tool (`openssl version` should report 3.x), for
  the dev certificates
- Docker with Compose, for `make run` and `make e2e`
- Node.js 20 or newer, for the control panel's JavaScript tests in `make test`

Create the virtual environment and install the dependencies:
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
  the browser warning). It shows each connected gateway's key exchange,
  flagging the classical ones, and the readers connected through it.
- Database editor (sqlite-web): http://127.0.0.1:8080
- Follow the readers deciding: `make logs SERVICE=reader-3`
- `gateway-2` stands in for a gateway without ML-KEM (classical `X25519`
  only), with `reader-5` behind it. The cloud falls back to `X25519` for it;
  uncomment the `KEY_EXCHANGE: hybrid-only` line in `docker-compose.yml` to see it
  refused (and `reader-5` failing closed).
- Every device and the cloud report their OpenSSL version. The images run
  Debian's 3.5.7, which is affected by the simulated ML-KEM vulnerability
  (SCRUM-45), so the panel flags all of them, and a hybrid gateway counts as
  classical in the stakeholder views. See [lib](lib/README.md#openssl-versions-libopenssl).
- Migrate: `make migrate` moves the cloud and both gateways to the
  `-openssl<version>` images, which have the fix, and the panel shows `gw-1`
  as hybrid again (the readers stay flagged). `make run` moves them back. See
  [OpenSSL image variants](#openssl-image-variants).
- Stop: `make stop`

All state lives in `data/` (gitignored): `data/certs/` and the SQLite database
`data/cloud/master.db`, which is seeded with the example data on first start.

### OpenSSL image variants

Until `python:3.15-slim` (Debian trixie) ships OpenSSL 3.5.8 or newer, the
cloud and gateway images come in two variants from one Dockerfile (SCRUM-55):

| Image | OpenSSL |
|---|---|
| `dev-course/cloud`, `dev-course/gateway` | the base image's (3.5.7, affected) |
| `dev-course/cloud:openssl3.5.9`, `dev-course/gateway:openssl3.5.9` | the version `openssl/openssl.env` pins, built from source and loaded ahead of Debian's `libssl` |

- `make build` builds both. `make migrate` moves the cloud and every gateway
  to the variants (`openssl/compose.migrated.yml`), on the scaled stack if it
  is running, else on the default stack. `make run` or `make run-scaled`
  moves them back.
- The scaled stack starts half migrated: its cloud and odd-numbered hybrid
  sites run the variants.
- Readers stay on the base image: their hop to the gateway is classical, so
  ML-KEM doesn't matter to them.
- **We update this OpenSSL ourselves**: Debian's security updates don't reach
  it. For a new OpenSSL release, bump `OPENSSL_VERSION` and `OPENSSL_SHA256`
  in `openssl/openssl.env` together (the checksum is the `.sha256` file OpenSSL
  publishes with the release).
- When the base image ships the fix itself, CI (`test.yml`) warns. Then the
  variants and the `openssl/` folder, which holds everything they need, can
  go.

### Scaled stack (opt-in)

`make run-scaled` starts the default stack plus 10 more sites, each a gateway
with 8 readers on a reader VLAN of its own; the last 2 sites' gateways have no
ML-KEM, like `gateway-2`. Set the size with make variables:

```bash
make run-scaled GATEWAYS=4 READERS=3 CLASSICAL=1
```

It uses the default stack's ports, so `make stop` first, and `make stop-scaled`
when done. `make migrate` moves its cloud and every gateway to the patched
OpenSSL. Device names, where its data lives and each site's traffic: see
[lib/README.md](lib/README.md#scaled-stack-libtopology).

## Repository layout

| Path | |
|---|---|
| `reader/`, `gateway/`, `cloud/` | one package + Dockerfile + README per component, run as `python -m <component>` |
| `lib/` | shared code: env config, TLS contexts, WebSocket hub, certificates, the scaled stack |
| `docs/` | the spec and architecture diagram, [CI/CD details](docs/ci.md), the [critical dependencies and libraries](docs/critical_dependencies.md), and the AI-usage records in `docs/ai/` |
| `tests/unit/<component>/` | unit tests, one directory per component; the panel's JavaScript tests in `tests/unit/cloud/static/` |
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
  per deployment with `KEY_EXCHANGE` (`hybrid`, `hybrid-only` or `classical`).
  The reader and admin hops stay on classical `X25519`. See [lib/README.md](lib/README.md#gateway--cloud-ml-kem-hybrid-with-classical-fallback).
- **Fail closed.** Any timeout, disconnect or malformed answer means no access.
- Env vars beyond the spec (ports, certificate paths, `KEYS`,
  `SCAN_INTERVAL_MIN`/`_MAX`, `DB_PATH`) all have defaults; see each
  component's README.

## Acknowledged risks (out of scope)

- The cloud does not authenticate gateways (no mutual TLS), and gateways don't
  authenticate readers.
- The reader → gateway hop has no post-quantum key exchange (per the spec).
- Gateway → cloud connections that fall back to classical `X25519` (an end
  without ML-KEM) can be recorded now and decrypted by a future quantum
  computer, until the cloud is switched to `KEY_EXCHANGE=hybrid-only`. The control
  panel lists which gateways those are.
- Certificates are classical (ECDSA P-256) on every hop.
- The control panel has no admin authentication.
- Physical access to the reader VLAN is assumed to be safe.
- Data at rest: the SQLite database (`data/cloud/master.db`) isn't encrypted;
  the host it runs on is assumed to be sufficiently secured.
- No gateway or cloud response caching for redundancy: the cloud being down
  means every door stays closed.

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

It runs the unit and integration tests in `tests/unit` and `tests/integration`,
then the control panel's JavaScript tests (`tests/unit/cloud/static/*.test.mjs`)
on Node's built-in test runner. Those load `cloud/static/app.js` and
`stakeholders.js` unchanged into a stand-in page (`panel.mjs`) and test their
pure functions; no npm packages are needed.

Run the end-to-end tests. They build the images, start the compose stack from
them and check it from outside, as the doors and an admin see it: decisions,
the key exchange of every hop, OpenSSL versions and the migration to the
patched images, panel edits, the cloud going down, the cloud switched to
hybrid-only. The stack gets its own certificates and database, so
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
| `release.yml` | a `v*` tag | the same checks, then builds the images (and the [OpenSSL variants](#openssl-image-variants)) for amd64 and arm64, runs the e2e tests on the amd64 ones and pushes them to the GitHub container registry |
| `test.yml` | called by both | lint and tests, in `python:3.15-slim`: its OpenSSL has ML-KEM, and the runner's doesn't (pytest would skip those tests). Warns when that OpenSSL has the ML-KEM fix, so the [variants](#openssl-image-variants) can go. Installs Debian's Node.js for the JavaScript tests |

A pull request may be merged once its `can-merge` check is green. GitHub
doesn't enforce that here (no branch protection for a private repository on
GitHub Free), so don't merge a red one.

To release, tag a commit on `main` with `v` and a SemVer version, and push the
tag:
```bash
git tag v1.0.0 origin/main
```
```bash
git push origin v1.0.0
```

Which tags are accepted, how the images are built and published, and how to
pull them: [docs/ci.md](docs/ci.md).
