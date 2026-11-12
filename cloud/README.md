# Cloud Server

Run with `python -m cloud`. It serves two TLS listeners from one process:

| Port | Protocol | For |
|---|---|---|
| 8443 | WSS (`websockets`, asyncio) | gateways, see [protocol](#gateway-protocol) |
| 8444 | HTTPS (`http.server`, own thread) | admin control panel + its JSON API |

Plain HTTP on port 8444 (`http://localhost:8444/...`) gets a `308` redirect to
the same URL over HTTPS. The panel tells the two apart by the first byte the
client sends (`0x16` starts a TLS handshake); a `308` keeps a POST a POST.

## Configuration

| Variable | Default | |
|---|---|---|
| `DB_PATH` | `/data/master.db` | SQLite file, created if missing |
| `TLS_CERT` / `TLS_KEY` | `/certs/server.pem` / `/certs/server.key` | server certificate for both ports |
| `GATEWAY_PORT` | `8443` | |
| `PANEL_PORT` | `8444` | |
| `KEY_EXCHANGE` | `hybrid` | key exchange with gateways (port 8443 only): `hybrid` (`X25519MLKEM768` with `X25519` fallback), `hybrid-only` (refuses classical gateways) or `classical`; anything else, or a leftover `OPENSSL_CONF`, stops the cloud at startup. See [lib](../lib/README.md#gateway--cloud-ml-kem-hybrid-with-classical-fallback) |

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
(`static/`) and refreshes every 5 s. A refresh redraws only the parts whose
data changed, so scroll positions, open or closed gateways, filters and text
being typed stay as they are.

The panel has two tabs, kept in the URL so a link opens the same place:
**Operations** (`#operations`, the default) with everything below, and
**Stakeholders** (`#stakeholders/<view>`) with a view per stakeholder of the
post-quantum migration (persona cards, 811373A):

| View | For | Shows |
|---|---|---|
| `cio` (default) | the CIO, and the key customer | green / amber / red status and the top three risks in plain language, without addresses or device names |
| `migration` | the PQC migration project manager | the readiness score as one number, and the gateways blocking it |
| `security` | the security officer | the quantum-vulnerable connections with the readers behind them and their share of recent traffic, what switching to `KEY_EXCHANGE=hybrid-only` would disconnect, and offline gateways. Never green while a classical connection remains |

Each view ends with "Your concerns": what the dashboard addresses for that
stakeholder, what it doesn't yet, and what it won't (policy decisions where
the stakeholders disagree, such as when to turn off classical fallback). The
views are drawn from `GET /api/summary` (`summary.py`), where the readiness
score and status rules live:

- **Readiness:** the share of connected gateways on post-quantum hybrid
  (offline gateways are not counted).
- **Status:** green when every known gateway is connected and on hybrid; red
  when a gateway is offline or more than half of the connected ones are
  classical; amber otherwise (including a key exchange the cloud couldn't
  read).
- "Recent traffic" is the newest 500 access events.

The views are a presentation choice, not access control: the panel has no
authentication, so the CIO view is safe to *show* a customer but the panel
must not be exposed to one.

The Operations tab is laid out to stay usable with many readers and gateways (try
`make run-scaled`, see the [root README](../README.md#scaled-stack-opt-in)):

- Tiles at the top count the connected gateways (of all known), those on
  classical key exchange, the readers and the keys.
- A toolbar that stays at the top of the window filters the readers by
  gateway and by reader ID or zone text. The filter applies to "Readers",
  "Room access" and "Group rooms".
- "Readers" lists them grouped by gateway, each group showing its reader count
  and the gateway's connection state. Groups can be opened and closed; with
  more than 20 readers they start closed, and a text search opens the groups
  it matches in.
- Wide or long tables scroll inside their own box, with the header rows and
  the key or group column kept in view. The room columns of the matrices are
  grouped under their gateway.

"Connected gateways" shows the key exchange of each gateway's connection:
post-quantum hybrid, or classical (in amber) for gateways without ML-KEM. A
line above the table counts the classical ones, which switching the cloud to
`KEY_EXCHANGE=hybrid-only` would disconnect.

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
| `GET /api/summary` | the stakeholder views' data: `readiness` (0–1, or `null` with nothing connected), `status` (`green`/`amber`/`red`), gateway counts (`known`, `connected`, `hybrid`, `classical`, `unknown`, `offline`), the `classical`, `unknown` and `offline` gateways (`id`, `key_exchange`, `readers`, `traffic_share`), `classical_traffic_share`, `hybrid_only_disconnects` (`gateways`, `readers`), `readers`, `recent_events` and `risks` (`severity`, `title`, `detail`, `gateways`), most severe first |
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
