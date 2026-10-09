# Cloud Server

Run with `python -m cloud`. It serves two TLS listeners from one process:

| Port | Protocol | For |
|---|---|---|
| 8443 | WSS (`websockets`, asyncio) | gateways, see [protocol](#gateway-protocol) |
| 8444 | HTTPS (`http.server`, own thread) | admin control panel + its JSON API |

## Configuration

| Variable | Default | |
|---|---|---|
| `DB_PATH` | `/data/master.db` | SQLite file, created if missing |
| `TLS_CERT` / `TLS_KEY` | `/certs/server.pem` / `/certs/server.key` | server certificate for both ports |
| `GATEWAY_PORT` | `8443` | |
| `PANEL_PORT` | `8444` | |
| `OPENSSL_CONF` | `/opt/lib/openssl/hybrid.cnf` (image) | key exchange with gateways (port 8443 only): hybrid `X25519MLKEM768` with `X25519` fallback; `hybrid-only.cnf` refuses classical gateways, see [lib](../lib/README.md#gateway--cloud-ml-kem-hybrid-with-classical-fallback) |

## Gateway protocol

A gateway opens `wss://<cloud>:8443` with a `Gateway-Id: <ID>` handshake header
and keeps the connection open. The cloud lists it under "connected gateways"
for as long as the connection lives. The ID is **not verified** (accepted risk
in the spec).

```jsonc
// gateway -> cloud: the reader's request plus the gateway's request_id
{"id": "key-bob", "reader_id": "rd-3", "request_id": "5f0c..."}
// cloud -> gateway
{"request_id": "5f0c...", "result": "pass"}   // or "fail"
```

Requests without string `id` and `reader_id` fields get `fail` and are not
logged.

## Database

- `schema.sql` creates the tables from the spec, plus `ACCESS_EVENTS`. It runs on
  every start (`CREATE TABLE IF NOT EXISTS`).
- `seed.sql` holds the example gateway, readers, groups and keys. It is loaded
  **only when the database file is brand new**, so edits made in the panel or
  sqlite-web survive restarts. To start over, stop the stack and delete `data/cloud/master.db`.
- Every authorization request is logged to `ACCESS_EVENTS` (timestamp, key,
  reader, zone, gateway, result). The zone is copied at scan time, so history
  stays correct if a reader is later moved to another zone. Unknown readers are
  logged with an empty zone.
- DB work runs in a worker thread (`asyncio.to_thread`), so a lock held by
  sqlite-web cannot stall the event loop.

## Control panel

Open `https://localhost:8444`. The browser will warn about the certificate
unless you trust `data/certs/ca.pem`. The panel is vanilla HTML/CSS/JS
(`static/`) and refreshes every 5 s.

"Connected gateways" shows the key exchange of each gateway's connection:
post-quantum hybrid, or classical (in amber) for gateways without ML-KEM. A
line above the table counts the classical ones, which switching the cloud to
`hybrid-only.cnf` would disconnect.

The panel edits group memberships, which decide access: a key opens a reader
when they share a group. "Room access" shows the result per key and reader.
Clicking a cell in "Key groups" (key × group) or "Group rooms" (group ×
reader) adds or removes that membership. Keys exist only through their groups,
so the panel lists every key in a group or seen at a reader; "Add key" adds a
row for a new key, kept only in the browser until it is put in a group.
Readers, gateways and the groups themselves are edited through sqlite-web
(`http://127.0.0.1:8080`).

| Endpoint | Returns |
|---|---|
| `GET /api/gateways` | connected gateways: `id`, `address`, `since`, `key_exchange` (the group the connection negotiated, e.g. `X25519MLKEM768`, or `null` if unknown) and `post_quantum` (`true` for an ML-KEM hybrid, `false` for classical) |
| `GET /api/readers` | readers with their `gateway_id` and `zone_name` |
| `GET /api/events?key=&reader=` | newest 100 access events, optionally filtered |
| `GET /api/access` | `keys` (in a group or seen at a reader), `groups`, and the memberships `key_groups` (`key_uuid`, `group_id`) and `reader_groups` (`reader_id`, `group_id`) |
| `POST /api/key-groups` | `204` once the key is in the group (`"member": true`) or out of it (`false`); body `{"key": "<id>", "group": "<id>", "member": <bool>}`. Any key ID is accepted |
| `POST /api/reader-groups` | the same for a reader, which must exist; body `{"reader": "<id>", "group": "<id>", "member": <bool>}` |

| Status | POST error (plain-text body) |
|---|---|
| `400` | invalid JSON, not an object, or a missing or mistyped field |
| `403` | `Origin` is not `https://<Host>` |
| `404` | unknown path, group or reader |
| `411` | no valid `Content-Length` |
| `413` | body over 4096 bytes (`MAX_BODY`) |
| `415` | `Content-Type` is not `application/json` |

The panel has **no authentication** (an accepted risk, see the root README):
anyone who can reach port 8444 can change who opens which door. The `403` and
`415` checks stop other web pages in the admin's browser from doing so (CSRF):
a cross-origin page can't send `application/json` without a CORS preflight,
which the server doesn't answer, and browsers send `Origin` with POSTs.
Requests without `Origin`, such as `curl`, are allowed. The panel renders all
data with `textContent`, because key and reader IDs come from unauthenticated
gateways.
