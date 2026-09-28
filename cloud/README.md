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
  **only when the database file is brand new**, so edits made through sqlite-web
  survive restarts. To start over, stop the stack and delete `data/cloud/master.db`.
- Every authorization request is logged to `ACCESS_EVENTS` (timestamp, key,
  reader, zone, gateway, result). The zone is copied at scan time, so history
  stays correct if a reader is later moved to another zone. Unknown readers are
  logged with an empty zone.
- DB work runs in a worker thread (`asyncio.to_thread`), so a lock held by
  sqlite-web cannot stall the event loop.

## Control panel

Open `https://localhost:8444`. The browser will warn about the certificate
unless you trust `data/certs/ca.pem`. The panel is read-only vanilla
HTML/CSS/JS (`static/`) and refreshes every 5 s. Edits are made through
sqlite-web (`http://127.0.0.1:8080`).

| Endpoint | Returns |
|---|---|
| `GET /api/gateways` | connected gateways: `id`, `address`, `since` |
| `GET /api/readers` | readers with their `gateway_id` and `zone_name` |
| `GET /api/events?key=&reader=` | newest 100 access events, optionally filtered |

The panel has **no authentication** (an accepted risk, see the root README).
It renders all data with `textContent`, because key and reader IDs come from
unauthenticated gateways.
