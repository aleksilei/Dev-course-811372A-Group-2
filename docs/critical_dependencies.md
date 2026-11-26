# Critical dependencies and libraries

The libraries and dependencies the system relies on for its security: the
Python packages (`requirements.txt` and `lib/pyproject.toml`) and what the
containers bring in implicitly (SCRUM-56). It is not a full bill of
materials, only what an attacker or a vulnerability in it would break.

Versions were read from the running containers on 2026-11-24 (`make run`,
images built from `python:3.15-slim`, Debian 13.8). See
[How to check](#how-to-check) to read them again.

## Summary

| # | Library / dependency | Version | Where | Why it is critical |
|---|---|---|---|---|
| 1 | **OpenSSL** (`libssl3`, `libcrypto3`) | 3.5.9 (updated from the vulnerable 3.5.7) | all images (cloud, gateway, reader) | All TLS: TLS 1.3, the hybrid X25519MLKEM768 key exchange, certificate checks |
| 2 | **CPython `ssl` module** | Python 3.15.2 | all images | The only binding to OpenSSL: builds every TLS context and picks the key-exchange groups |
| 3 | **websockets** | 17.4 (pinned) | all images, via `lib` | The only third-party runtime package: every reader → gateway and gateway → cloud message |
| 4 | **SQLite** (`libsqlite3`, Python `sqlite3`) | 3.46.1 | cloud | Stores keys, access rights and the access and connection history |
| 5 | **Python `http.server`** | Python 3.15.2 | cloud | Serves the admin control panel and its API (port 8444) |
| 6 | **Base image** `python:3.15-slim` | Debian 13.8 | all images | Brings OpenSSL, CPython, SQLite and glibc; an unpinned tag |
| 7 | **OpenSSL source build** (`openssl/build-openssl.sh`) | 3.5.9, SHA-256 pinned | `-openssl<version>` cloud and gateway images | Replaces the base image's OpenSSL when it is vulnerable (SCRUM-55) |
| 8 | **OpenSSL CLI** on the host | 3.x | `make certs` (`lib.certs`) | Generates the dev CA and the server certificates and keys |
| 9 | **coleifer/sqlite-web** | `latest` (unpinned) | `sqlite-web` service | Full, unauthenticated read and write access to the cloud database |

The Python packages in `requirements.txt` are development tools only (see
[below](#development-and-ci-requirementstxt)); none of them is in a container.

## Python dependencies

### Runtime (`lib/pyproject.toml`)

- **websockets 17.4**, the only third-party package installed in the images
  (`pip install /opt/lib`). Every connection in the system is a WebSocket
  over TLS (`websockets.asyncio.server` in the gateway and cloud,
  `websockets.asyncio.client` in the reader and gateway). It parses the HTTP
  upgrade request, including the `Gateway-Id`, `Reader-Id` and
  `OpenSSL-Version` headers, and every frame from peers that are **not authenticated**, so a
  parsing bug in it is reachable by anyone who can connect. It passes the
  `ssl.SSLContext` from `lib.tls` to asyncio, so TLS itself is OpenSSL's.
  Pinned to an exact version; upgrades are deliberate.

### Development and CI (`requirements.txt`)

`astroid`, `dill`, `iniconfig`, `isort`, `mccabe`, `mypy_extensions`,
`packaging`, `platformdirs`, `pluggy`, `Pygments`, `pylint`, `pytest`, `ruff`
and `tomlkit` are the linters and the test runner, with their own
dependencies. They run on developer machines and in CI, never in the images,
so they do not affect the running system. They matter only as a supply-chain
risk for CI (a compromised package runs with the workflow's permissions);
they are pinned to exact versions for that reason.

## Implicit in the containers

### OpenSSL

The most critical library. Python's `ssl` module links `libssl.so.3` and
`libcrypto.so.3` dynamically, and everything the system promises about
encryption is OpenSSL's work:

- TLS 1.3 on every hop (reader → gateway, gateway → cloud, browser → panel);
- the **X25519MLKEM768** hybrid key exchange on the gateway → cloud hop
  (`lib.tls`, `SSLContext.set_groups()`), and the classical X25519 fallback;
- certificate and hostname verification against the dev CA.

A vulnerability in its ML-KEM makes the hybrid key exchange no stronger than
classical: the simulated advisory (SCRUM-45) affects every version before
3.5.8, and `lib/src/lib/openssl.py` checks each device's reported version
against it (SCRUM-51). Readers and gateways report their version in the
`OpenSSL-Version` header, and the panel shows every version, and the cloud's
own, in the Operations tab and the security officer view.

- The old version was 3.5.7, the base image's, which has the ML-KEM
  vulnerability. The updated version is 3.5.9, which is patched.
- Cloud and gateway: the base image's OpenSSL, or, in
  the `-openssl<version>` images, OpenSSL 3.5.9 built from source into
  `/opt/openssl/lib` and loaded ahead of Debian's (see
  [the OpenSSL source build](#the-openssl-source-build)).
- Reader: always Debian's; there is no `-openssl` reader image.

### CPython and its `ssl` module

The binding between the code and OpenSSL. `lib.tls` builds every
`SSLContext`: minimum TLS version, the key-exchange groups, certificate
verification. A CPython bug in `ssl` (or a Python built against an old
OpenSSL) weakens every link the same way an OpenSSL bug would. Comes from the
base image; the version is whatever `python:3.15-slim` ships when the image is
built.

### SQLite

The cloud's database (`/data/master.db`, `cloud/db.py`) holds the keys, the
rooms and groups that decide whether a door opens, and the access and gateway
connection history the Logs tab and the readiness score use. Its integrity is
the integrity of the access decisions. Python's `sqlite3` module links
Debian's `libsqlite3-0` (3.46.1). Values from requests are passed as query
parameters, never built into SQL, so the risk is in the library itself.

### Python `http.server`

The admin control panel (`cloud/panel.py`) is the standard library's
`ThreadingHTTPServer` behind TLS. It has no authentication, so it relies on
being reachable only by admins (port 8444). The standard library documents
`http.server` as not meant for production; a bug in it is a bug in the panel.

### The base image, `python:3.15-slim`

Every image starts from it, and it brings OpenSSL, CPython, SQLite and glibc
(2.41) with it. It is referenced by tag, not by digest, so a rebuild can pick
up a different OpenSSL. That is how Debian's security updates arrive, but it
also means a rebuild is not reproducible.

### The OpenSSL source build

`openssl/build-openssl.sh` downloads the release in `openssl/openssl.env` from
GitHub, checks it against the pinned SHA-256 and builds it in a separate build
stage. Its tools (`build-essential`, `curl`, `perl`) stay out of the final
image. The checksum is what protects this step: bump the version and checksum
together. This is how the cloud and gateways were updated from the vulnerable
3.5.7 to 3.5.9 (`make migrate`).

### The OpenSSL command line on the host

`make certs` runs `python -m lib.certs`, which calls the `openssl` command on
the developer's machine to make the dev CA and the server keys and
certificates in `data/certs/`. Those keys protect every TLS link, so the host's
OpenSSL matters too, and `data/certs/ca.key` is the most sensitive file in the
repository's working tree (gitignored).

### `coleifer/sqlite-web`

A third-party image, pulled as `latest`, with unauthenticated read and write
access to the cloud database. It is bound to `127.0.0.1:8080` only, so it is a
local development tool, but whoever reaches that port can change access
rights. Not needed by the system itself; pin it or leave it out of any
deployment.

## Not critical

Libraries in the images that the system does not rely on for security, left
out above: `pip` and `setuptools` (only used while building), `zlib`,
`ca-certificates` (the system trusts its own dev CA, not the public CAs; only
the OpenSSL source build uses them), and the standard library modules for
logging, JSON, asyncio, `random` (the reader's simulated scans, not a security
use) and so on.

## How to check

The versions in a running container (replace `cloud-1` with
`gateway-1-1` or `reader-1-1`):

```bash
docker exec dev-course-811372a-group-2-cloud-1 python -c "import ssl, sqlite3, sys, websockets; print(sys.version, ssl.OPENSSL_VERSION, sqlite3.sqlite_version, websockets.__version__, sep='\n')"
```

The Debian packages behind them:

```bash
docker exec dev-course-811372a-group-2-cloud-1 dpkg-query -W libssl3t64 openssl libsqlite3-0 libc6
```

The OpenSSL version every connected reader and gateway reports, and the
cloud's own, are also in the control panel (Operations tab, and Stakeholders →
Security officer).
