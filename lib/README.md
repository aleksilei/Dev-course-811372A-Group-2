# lib

Code shared by the cloud, gateway and reader. Installed into each image (and
into the dev venv by `make install`); it also pins the one runtime dependency,
`websockets`.

| Module | Contents |
|---|---|
| `lib.config` | `env(name, default=None)`: reads an environment variable; without a default it is required (`ConfigError`). `setup_logging()`. |
| `lib.tls` | `server_context()` / `client_context()` and the key-exchange groups of each hop (`gateway_cloud()` reads the gateway → cloud ones from `KEY_EXCHANGE`). `negotiated_group()` / `is_post_quantum()` for what a connection negotiated. |
| `lib.hub` | `Hub`: the server end of a WebSocket hop (see below). |
| `lib.certs` | Dev CA and server certificates (`make certs`). |
| `lib.topology` | The opt-in scaled stack (`make run-scaled`): writes a compose override with extra gateway sites, their certificates and the seed data into `data-scaled/`. Host-side only. See the [root README](../README.md#scaled-stack-opt-in). |

## TLS (`lib.tls`)

Every TLS context in the system comes from `server_context(cert, key, groups)`
or `client_context(ca, groups)`. Both require TLS 1.3 and offer and accept only
`groups`, an OpenSSL group list set with `SSLContext.set_groups()` (Python
3.15). Clients verify the server certificate against the dev CA; servers don't
ask for client certificates (no mutual TLS, per the spec).

The key-exchange groups are chosen per hop, matching the spec's communication
table:

| Groups | Hop | Key exchange |
|---|---|---|
| `READER_GATEWAY` | reader → gateway | `X25519`, pinned |
| `gateway_cloud()` | gateway → cloud | from `KEY_EXCHANGE`, default hybrid `X25519MLKEM768` with `X25519` fallback: see [below](#gateway--cloud-ml-kem-hybrid-with-classical-fallback) |
| `ADMIN_CLOUD` | browser → control panel | `X25519`, pinned |

Pinning matters even for classical TLS: OpenSSL ≥ 3.5, which ships in the
`python:3.15-slim` images, prefers the post-quantum hybrid `X25519MLKEM768`
whenever both ends support it. The tests in `tests/unit/lib/test_tls.py` check
that the server accepts, and the client offers, nothing but the pinned group.

### Gateway → cloud: ML-KEM hybrid with classical fallback

This hop uses the hybrid `X25519MLKEM768` (X25519 + ML-KEM-768) and falls back
to classical `X25519` when the other end has no ML-KEM, so upgraded and older
gateways and clouds keep working together. TLS negotiates the group during the
handshake, so nothing above `lib.tls` changes.

The gateway and the cloud read the mode from the `KEY_EXCHANGE` environment
variable through `gateway_cloud()`, which logs it at startup:

| `KEY_EXCHANGE` | Offers and accepts | For |
|---|---|---|
| `hybrid` (default) | `X25519MLKEM768`, falling back to `X25519` | a fleet where not everything is upgraded yet |
| `hybrid-only` | `X25519MLKEM768` only | once every gateway and the cloud are upgraded: classical peers are refused |
| `classical` | `X25519` only | what software from before ML-KEM does: rollback, and `gateway-2` in `docker-compose.yml` |

The group a gateway and the cloud end up with (`test_gateway_cloud_key_exchange`):

| Gateway ↓ / Cloud → | hybrid | hybrid-only | classical or before ML-KEM |
|---|---|---|---|
| hybrid | `X25519MLKEM768` | `X25519MLKEM768` | `X25519` |
| hybrid-only | `X25519MLKEM768` | `X25519MLKEM768` | no connection |
| classical or before ML-KEM | `X25519` | no connection | `X25519` |

- Any other `KEY_EXCHANGE` stops the process at startup (`ConfigError`), so a
  typo can't weaken the key exchange. So does a leftover `OPENSSL_CONF` from
  the Python 3.13 version, whose config files are gone: OpenSSL would silently
  ignore the missing file, and a cloud meant to be hybrid-only would accept
  classical gateways.
- Both ends need OpenSSL ≥ 3.5 for ML-KEM (the images have it).
- On the wire, `hybrid` is the same as the Python 3.13 version with
  `hybrid.cnf`, and `classical` the same as `classical.cnf` or v1, so the
  matrix holds for mixed fleets during an upgrade.
- The `*` in `*X25519MLKEM768:*X25519` makes the client send a key share for
  both groups in its first message, so a classical cloud costs no extra round
  trip (HelloRetryRequest). The hybrid adds about 1.2 KB to each direction of
  the handshake, once per connection.
- An attacker can't strip the hybrid group between two upgraded ends: the
  server signs the handshake transcript, which includes the groups the client
  offered. Connections that fall back to `X25519` can still be recorded now and
  decrypted by a future quantum computer, which is what `hybrid-only` is for.
  Certificates stay ECDSA P-256: ML-KEM protects confidentiality, not
  authentication.

### Which group a connection negotiated

`negotiated_group(ssl_object)` returns the group of a connection (e.g.
`'X25519MLKEM768'`), or `None` before the handshake, and `is_post_quantum(group)`
says whether it includes ML-KEM. `Hub` lists it per client, the control panel
shows it per gateway, and the gateway logs the one it got from the cloud.
websockets exposes the `SSLObject` as
`ws.transport.get_extra_info('ssl_object')`.

It is `SSLObject.group()` (Python 3.15), with one change: OpenSSL spells
`x25519` in lower case but `X25519MLKEM768` in mixed case, so the groups of
this system are reported as `X25519` and `X25519MLKEM768`, the names the
control panel API has always used. Other groups are reported as OpenSSL
spells them.

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
