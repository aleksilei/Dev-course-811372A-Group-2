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
in the spec). Neither is the gateway's `OpenSSL-Version` header (e.g.
`OpenSSL 3.5.7 9 Jun 2026`), which the panel checks for known vulnerabilities
(see [lib](../lib/README.md#openssl-versions-libopenssl)); without it, or with
a version the cloud can't check, the gateway is assumed vulnerable.

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
- `GATEWAY_CONNECTIONS` stores every gateway-to-cloud session: gateway ID,
  remote address, negotiated key-exchange group, whether it is post-quantum,
  and its connected and disconnected UTC timestamps. An empty disconnect time
  means the session is still open. The cloud closes any leftover open sessions
  at startup so a previous process crash cannot make them appear live forever.
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

The panel has three tabs, kept in the URL so a link opens the same place:
**Operations** (`#operations`, the default), **Logs** (`#logs`) and
**Stakeholders** (`#stakeholders/<view>`) with a view per stakeholder of the
post-quantum migration (persona cards, 811373A):

| View | For | Shows |
|---|---|---|
| `cio` (default) | the CIO, and the key customer | green / amber / red status and the top three risks in plain language, without addresses or device names |
| `migration` | the PQC migration project manager | traffic-weighted PQC readiness, gateway coverage, and the gateways blocking it |
| `security` | the security officer | the quantum-vulnerable connections with the readers behind them and their share of last-hour traffic, what switching to `KEY_EXCHANGE=hybrid-only` would disconnect, offline gateways, and the encryption status of every device (see below). Never green while a classical connection remains |

Each view ends with "Your concerns": what the dashboard addresses for that
stakeholder, what it doesn't yet, and what it won't (policy decisions where
the stakeholders disagree, such as when to turn off classical fallback). The
views are drawn from `GET /api/summary` (`summary.py`), where the readiness
score and status rules live:

- **PQC traffic readiness:** the share of all access events in the last hour
  recorded with hybrid key exchange and OpenSSL 3.5.8 or newer at both ends of
  the gateway-to-cloud connection. Classical links, affected versions and
  missing or unreadable details count against readiness. The score is `null`
  when the window has no events. Each event keeps its negotiated group and
  both OpenSSL versions, so reconnecting, upgrading or disconnecting a gateway
  does not change how its earlier traffic counts. Existing databases gain the
  new columns automatically and keep their access history.
- **Gateway coverage:** the share of connected gateways confirmed to use
  post-quantum hybrid key exchange (offline gateways are not counted).
- **Status:** green when every known gateway is connected and on hybrid; red
  when a gateway is offline or more than half of the connected ones are
  classical or weakened; amber otherwise (including a key exchange the cloud
  couldn't read).
- **Weakened gateways** (SCRUM-51): a gateway that negotiated hybrid key
  exchange, but where the OpenSSL at either end of the link, its own or the
  cloud's, has an ML-KEM advisory or can't be confirmed patched. Its ML-KEM
  can't be trusted, so it is no stronger than classical: it doesn't count
  towards gateway coverage (or the CIO's "protected" gateways), counts like a
  classical gateway for the status, and is a top risk ("The cloud runs a
  vulnerable OpenSSL" when the cloud's end is the cause) and a migration
  blocker. Switching to `KEY_EXCHANGE=hybrid-only` would not cut it off.
- Traffic scores use access events from the rolling last hour. The security
  officer view shows the non-PQC share alongside the per-gateway breakdown.

The security officer view ends with the **encryption status of every
device** (`GET /api/devices`, `devices.py`): each registered or connected
gateway and reader, with the TLS version, cipher suite and key exchange of its
own link and, for a reader, of its gateway's link to the cloud. Counts per
status sit above the table, and a line below gives the panel's own link (the
browser's connection to the panel). A device's status is its weakest link:

- `post-quantum`: every link is a post-quantum hybrid;
- `classical`: some link is classical. Every reader is, because the reader →
  gateway hop is classical by the spec;
- `unknown`: a key exchange the cloud couldn't read, an unregistered device
  (its links are still shown), or a reader behind a gateway that is offline or
  doesn't report its readers;
- `offline`: a gateway that isn't connected, or a reader its reporting gateway
  doesn't list.

Nothing the cloud can't confirm is shown as encrypted.

The views are a presentation choice, not access control: the panel has no
authentication, so the CIO view is safe to *show* a customer but the panel
must not be exposed to one.

The **Logs** tab combines the gateway connection history and the existing
access history. It shows the newest 100 gateway sessions, optionally filtered by
gateway before applying the limit; classical key-exchange groups are highlighted
in amber. An empty disconnect time means the session is current. Access history keeps its key and
reader filters.

The Operations tab is laid out to stay usable with many readers and gateways (try
`make run-scaled`, see the [root README](../README.md#scaled-stack-opt-in)):

- Tiles at the top count the connected gateways (of all known), those on
  classical key exchange, the connected readers (of all registered), any
  unregistered readers that are connected, the connected devices (and the
  cloud) on a vulnerable OpenSSL (amber when any), and the keys.
- A toolbar that stays at the top of the window filters the readers by
  gateway and by reader ID or zone text. The filter applies to "Readers",
  "Room access" and "Group rooms".
- "Readers" lists them grouped by gateway, each group showing how many of its
  readers are connected and the gateway's connection state. Groups can be
  opened and closed; with more than 20 readers they start closed, and a text
  search opens the groups it matches in.
- Each reader's **Connection**, from `/api/devices` (hover for the address
  and key exchange), worded the same as in the security officer's device
  list:
  - `connected since …` (green);
  - `connected via gw-X since …` (amber): connected through another gateway
    than the database says;
  - `…, not registered: its scans fail` (amber): connected, but not in the
    database. Listed under the gateway it's connected to, and left out of
    the matrices;
  - `not connected` (red): its gateway reports it isn't;
  - `unknown` (grey): its gateway is offline, or doesn't report its readers.

  Reader IDs are taken on trust, like gateway IDs. Reader connections are live
  reports from gateways; only gateway-to-cloud sessions are kept as history.
- Each reader's and gateway's **OpenSSL** column shows the version it reports
  (SCRUM-51). A vulnerable one is amber and marked `: vulnerable` (hover for
  the advisory). A connected device that reports none is amber
  `not reported: assumed vulnerable`, and one with a version the cloud can't
  check is amber `…: can't check, assumed vulnerable`. A device that isn't
  connected shows `–`.
- Wide or long tables scroll inside their own box, with the header rows and
  the key or group column kept in view. The room columns of the matrices are
  grouped under their gateway.

"Connected gateways" shows the key exchange of each gateway's connection:
post-quantum hybrid, or classical (in amber) for gateways without ML-KEM. A
line above the table counts the classical ones, which switching the cloud to
`KEY_EXCHANGE=hybrid-only` would disconnect, and the weakened ones, whose
hybrid key exchange is no stronger than classical. A second line gives the
cloud's own OpenSSL, which ends every gateway link.

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
| `GET /api/gateways` | connected gateways: `id`, `address`, `since`, `key_exchange` (the group the connection negotiated, e.g. `X25519MLKEM768`, or `null` if unknown), `post_quantum` (`true` for an ML-KEM hybrid, `false` for classical), `tls_version` and `cipher` of the connection, the OpenSSL fields (`openssl`: the reported version or `null`; `openssl_checked`: whether the cloud could check it; `openssl_vulnerable`: `true` when an advisory matches or it couldn't be checked; `openssl_affects`: what the advisories break, e.g. `["ml-kem"]`; `openssl_advisory`: why), `weakened` (hybrid, but with a vulnerable ML-KEM at either end), and `readers`: the readers connected to the gateway (`id`, `address`, `since`, `tls_version`, `cipher`, `key_exchange`, `post_quantum` and the OpenSSL fields), or `null` if the gateway hasn't reported them |
| `GET /api/devices` | every gateway and reader: `statuses`, `counts` per type (`gateway`, `reader`) and status, `devices` (`id`, `type`, `gateway`, `registered`, `state`, `status`, `address` and `since` of its connection, the OpenSSL fields as in `/api/gateways` (all `null` for a device that isn't connected; never part of `status`), for readers `registered_gateway` and `zone_name` from the database, and `links`: each `name`, `tls_version`, `cipher`, `key_exchange`, `post_quantum`; a reader's own link first, then its gateway's), `panel`, the request's own link, and `cloud`, the OpenSSL fields of the cloud itself |
| `GET /api/connections?gateway=` | newest 100 gateway-to-cloud connections, optionally filtered by gateway before limiting; each row has `gateway_id`, `address`, `key_exchange`, `post_quantum`, `connected_at` and `disconnected_at` (null while connected) |
| `GET /api/summary` | the stakeholder views' data: `readiness` (traffic weighted, 0–1 or `null` with no recent events), `gateway_coverage` (0–1 or `null` with no connected gateways), `non_pqc_traffic_share`, `status` (`green`/`amber`/`red`), gateway counts (`known`, `connected`, `hybrid`, `weakened`, `classical`, `unknown`, `offline`; `hybrid` leaves out the weakened ones), the `classical`, `weakened` (also with `openssl`), `unknown` and `offline` gateways (`id`, `key_exchange`, `readers`, `traffic_share`), `classical_traffic_share`, `hybrid_only_disconnects` (`gateways`, `readers`), `readers`, `recent_events` (events in the last hour), `cloud` (the cloud's OpenSSL fields) and `risks` (`severity`, `title`, `detail`, `gateways`), most severe first |
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
