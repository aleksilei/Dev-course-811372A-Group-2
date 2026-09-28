# Dev-course-811372A-Group-2

Simulated NFC door access system: **Access Readers** ask an **Edge Gateway**,
which relays to the **Cloud Server**, whether a key may pass. The spec and
architecture diagram are in [`docs/`](docs/system_spec.md).

```
reader-1..4 --WSS--> gateway-1 --WSS--> cloud  <--HTTPS-- admin (control panel)
   (reader-vlan, internal)        (wan)          sqlite-web on 127.0.0.1:8080
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
  the browser warning)
- Database editor (sqlite-web): http://127.0.0.1:8080
- Follow the readers deciding: `make logs SERVICE=reader-3`
- Stop: `make stop`

All state lives in `data/` (gitignored): `data/certs/` and the SQLite database
`data/cloud/master.db`, which is seeded with the example data on first start.

## Repository layout

| Path | |
|---|---|
| `reader/`, `gateway/`, `cloud/` | one package + Dockerfile + README per component, run as `python -m <component>` |
| `lib/` | shared code: env config, TLS contexts, WebSocket hub, certificates |
| `*/test/` | unit tests per component |
| `test/` | integration tests: readers → gateway → cloud over real TLS |

## Implementation decisions

- **WebSockets on both hops.** The upper components don't know the addresses of
  the ones below, so clients connect upwards and servers keep the connections
  in memory (`lib.hub`). All WebSocket code uses the asyncio API of the
  `websockets` package.
- **Classical TLS 1.3 (X25519) on every hop in this version.** The gateway →
  cloud hop moves to ML-KEM in v2, which is a change in `lib.tls` (see
  [lib/README.md](lib/README.md)).
- **Fail closed.** Any timeout, disconnect or malformed answer means no access.
- Env vars beyond the spec (ports, certificate paths, `KEYS`, `SCAN_INTERVAL`,
  `DB_PATH`) all have defaults; see each component's README.

## Acknowledged risks (out of scope)

- The cloud does not authenticate gateways (no mutual TLS), and gateways don't
  authenticate readers.
- Neither hop uses post-quantum key exchange yet.
- The control panel has no admin authentication.
- Physical access to the reader VLAN is assumed to be safe.
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

`async def` tests run through a small hook in `conftest.py`, with no pytest
plugin needed.

You can run pylint and ruff with
```bash
make lint
```

or with the fix parameter for ruff (automagically fixes some issues)
```bash
make fix
```
