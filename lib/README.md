# lib

Code shared by the cloud, gateway and reader. Installed into each image (and
into the dev venv by `make install`); it also pins the one runtime dependency,
`websockets`.

| Module | Contents |
|---|---|
| `lib.config` | `env(name, default=None)`: reads an environment variable; without a default it is required (`ConfigError`). `setup_logging()`. |
| `lib.tls` | `server_context()` / `client_context()` and the key-exchange group of each hop (the gateway → cloud groups are in the OpenSSL configs in `openssl/`). `negotiated_group()` / `is_post_quantum()` for what a connection negotiated. |
| `lib.hub` | `Hub`: the server end of a WebSocket hop (see below). |
| `lib.certs` | Dev CA and server certificates (`make certs`). |

## TLS (`lib.tls`)

Every TLS context in the system comes from `server_context(cert, key, group)` or
`client_context(ca, group)`. Both require TLS 1.3. Clients verify the server
certificate against the dev CA; servers don't ask for client certificates (no
mutual TLS, per the spec).

The key-exchange group is chosen per hop, matching the spec's communication
table:

| Constant | Hop | Key exchange |
|---|---|---|
| `READER_GATEWAY` | reader → gateway | `X25519`, pinned |
| `GATEWAY_CLOUD` | gateway → cloud | `None`: hybrid `X25519MLKEM768` with `X25519` fallback, from the [OpenSSL config](#gateway--cloud-ml-kem-hybrid-with-classical-fallback) |
| `ADMIN_CLOUD` | browser → control panel | `X25519`, pinned |

A pinned group is the only one the context offers or accepts. Pinning matters
even for classical TLS: OpenSSL ≥ 3.5, which ships in the `python:3.13-slim`
images, prefers the post-quantum hybrid `X25519MLKEM768` whenever both ends
support it. The tests in `tests/unit/lib/test_tls.py` check that the server accepts,
and the client offers, nothing but the pinned group.

### Gateway → cloud: ML-KEM hybrid with classical fallback

This hop uses the hybrid `X25519MLKEM768` (X25519 + ML-KEM-768) and falls back
to classical `X25519` when the other end has no ML-KEM, so upgraded and older
gateways and clouds keep working together. TLS negotiates the group during the
handshake, so nothing above `lib.tls` changes.

Python 3.13's `SSLContext.set_ecdh_curve()` only knows classical curves
(`set_groups()` is new in Python 3.15), so this hop isn't pinned in code.
Instead, the gateway and cloud images load one of the configs in
[`openssl/`](openssl/) through the `OPENSSL_CONF` environment variable. The
config applies to the whole process, but the pinned contexts above override it,
so the reader port and the control panel stay classical.

| `OPENSSL_CONF` | Offers and accepts | For |
|---|---|---|
| `/opt/lib/openssl/hybrid.cnf` (image default) | `X25519MLKEM768`, falling back to `X25519` | a fleet where not everything is upgraded yet |
| `/opt/lib/openssl/hybrid-only.cnf` | `X25519MLKEM768` only | once every gateway and the cloud are upgraded: classical peers are refused |
| `/opt/lib/openssl/classical.cnf` | `X25519` only | what software from before ML-KEM does: rollback, and `gateway-2` in `docker-compose.yml` |

The group a gateway and the cloud end up with (`test_gateway_cloud_key_exchange`
runs each pair in separate processes and reads the group from the ServerHello):

| Gateway ↓ / Cloud → | hybrid | hybrid-only | before ML-KEM |
|---|---|---|---|
| hybrid | `X25519MLKEM768` | `X25519MLKEM768` | `X25519` |
| hybrid-only | `X25519MLKEM768` | `X25519MLKEM768` | no connection |
| classical or before ML-KEM | `X25519` | no connection | `X25519` |

- Both ends need OpenSSL ≥ 3.5 for ML-KEM (the images have it). The configs set
  `config_diagnostics = 1`, so a typo, or an OpenSSL without ML-KEM, stops the
  process at startup instead of silently using OpenSSL's default groups.
  `lib.tls` likewise refuses an `OPENSSL_CONF` file that doesn't exist (OpenSSL
  would ignore it). Without `OPENSSL_CONF`, e.g. `python -m gateway` from the
  venv, the hop uses OpenSSL's built-in group list and a warning is logged.
- The `*` in `*X25519MLKEM768:*X25519` makes the client send a key share for
  both groups in its first message, so a classical cloud costs no extra round
  trip (HelloRetryRequest). The hybrid adds about 1.2 KB to each direction of
  the handshake, once per connection.
- An attacker can't strip the hybrid group between two upgraded ends: the
  server signs the handshake transcript, which includes the groups the client
  offered. Connections that fall back to `X25519` can still be recorded now and
  decrypted by a future quantum computer, which is what `hybrid-only.cnf` is
  for. Certificates stay ECDSA P-256: ML-KEM protects confidentiality, not
  authentication.

### Which group a connection negotiated

`negotiated_group(ssl_object)` returns the group of a connection made from
these contexts (e.g. `'X25519MLKEM768'`), or `None` if it isn't known, and
`is_post_quantum(group)` says whether it includes ML-KEM. `Hub` lists it per
client, the control panel shows it per gateway, and the gateway logs the one
it got from the cloud. websockets exposes the `SSLObject` as
`ws.transport.get_extra_info('ssl_object')`.

Python 3.13 has no API for this (`SSLObject.group()` is new in 3.15), so every
context from `lib.tls` gets CPython's private debug hook,
`SSLContext._msg_callback`, which sees each handshake message. `_record_group()`
reads the group from the key_share extension of the ServerHello, which the
server writes and the client reads, and keeps it per connection in a
`WeakKeyDictionary` (entries go away with their connection). The hook runs
inside OpenSSL's handshake, so it never raises: a ServerHello it can't read
only makes the group `None`.

The move to Python 3.15 replaces both workarounds, the OpenSSL configs and the
debug hook, with public APIs: see
[Next step: Python 3.15](../README.md#next-step-python-315).

## `Hub`

Servers keep their clients' connections in memory because the upper
components don't know the addresses of the ones below them. A `Hub` subclass
sets `id_header` (the handshake header naming the client, e.g. `Gateway-Id`)
and implements `async respond(request, client_id) -> reply`. `Hub.handle` is the
`websockets` connection handler: it registers the client, answers every JSON
message with `respond()` (malformed JSON gets `{"result": "fail"}`), and lists
live clients through `connected()`, with the key-exchange group each one
negotiated. The ID is taken on trust.

Everything WebSocket-related uses the `websockets` **asyncio** API, so all TLS
I/O happens on one event-loop thread. The library's threaded API was dropped
because it reads and writes one OpenSSL connection from two threads, which
crashed the process under load.

## Certificates (`lib.certs`)

```bash
make certs    # = venv/bin/python -m lib.certs data/certs
```

This writes `ca.pem`/`ca.key` plus `gateway.*`, `gateway-2.*` and `cloud.*` to
`data/certs/` (gitignored). The SANs match `docker-compose.yml`: the gateways'
static IPs `10.10.0.10` and `10.10.0.11`, the hostname `cloud`, and `localhost`. It needs the **OpenSSL 3**
command line tool (`openssl version` should report 3.x). The tests use the
same function for throwaway certificates.
