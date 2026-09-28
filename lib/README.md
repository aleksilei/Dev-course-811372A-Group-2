# lib

Code shared by the cloud, gateway and reader. Installed into each image (and
into the dev venv by `make install`); it also pins the one runtime dependency,
`websockets`.

| Module | Contents |
|---|---|
| `lib.config` | `env(name, default=None)`: reads an environment variable; without a default it is required (`ConfigError`). `setup_logging()`. |
| `lib.tls` | `server_context()` / `client_context()` and the key-exchange group of each hop. |
| `lib.hub` | `Hub`: the server end of a WebSocket hop (see below). |
| `lib.certs` | Dev CA and server certificates (`make certs`). |

## TLS (`lib.tls`)

Every TLS context in the system comes from `server_context(cert, key, group)` or
`client_context(ca, group)`. Both require TLS 1.3 and allow exactly one
key-exchange group. Clients verify the server certificate against the dev CA;
servers don't ask for client certificates (no mutual TLS, per the spec).

The group is chosen per hop, matching the spec's communication table:

| Constant | Hop | Now |
|---|---|---|
| `READER_GATEWAY` | reader → gateway | `X25519` |
| `GATEWAY_CLOUD` | gateway → cloud | `X25519` |
| `ADMIN_CLOUD` | browser → control panel | `X25519` |

Pinning the group matters even for classical TLS: OpenSSL ≥ 3.5, which ships
in the `python:3.13-slim` images, prefers the post-quantum hybrid
`X25519MLKEM768` whenever both ends support it. The tests in
`lib/test/test_tls.py` check that the server accepts, and the client offers,
nothing but the pinned group.

### Moving the gateway → cloud hop to ML-KEM (v2)

1. Set `GATEWAY_CLOUD = 'X25519MLKEM768'`.
2. `_restrict()` uses `SSLContext.set_ecdh_curve()`, which only knows classical
   curves. Switch it to `SSLContext.set_groups(group)` (Python 3.15+, which
   also adds `SSLSocket.group()` for logging the negotiated group) and bump the
   images and venv to 3.15. On Python ≤ 3.14, the alternative is an
   `openssl.cnf` with `Groups = X25519MLKEM768`, loaded through the
   `OPENSSL_CONF` environment variable (this applies to the whole process).
3. Both ends need OpenSSL ≥ 3.5 (already true for the images).

## `Hub`

Servers keep their clients' connections in memory because the upper
components don't know the addresses of the ones below them. A `Hub` subclass
sets `id_header` (the handshake header naming the client, e.g. `Gateway-Id`)
and implements `async respond(request, client_id) -> reply`. `Hub.handle` is the
`websockets` connection handler: it registers the client, answers every JSON
message with `respond()` (malformed JSON gets `{"result": "fail"}`), and lists
live clients through `connected()`. The ID is taken on trust.

Everything WebSocket-related uses the `websockets` **asyncio** API, so all TLS
I/O happens on one event-loop thread. The library's threaded API was dropped
because it reads and writes one OpenSSL connection from two threads, which
crashed the process under load.

## Certificates (`lib.certs`)

```bash
make certs    # = venv/bin/python -m lib.certs data/certs
```

This writes `ca.pem`/`ca.key` plus `gateway.*` and `cloud.*` to `data/certs/`
(gitignored). The SANs match `docker-compose.yml`: the gateway's static IP
`10.10.0.10`, the hostname `cloud`, and `localhost`. It needs the **OpenSSL 3**
command line tool: `brew install openssl` on macOS, because the system
`/usr/bin/openssl` is LibreSSL. The tests use the same function for throwaway
certificates.
