# System Specification: PQC-Hybrid Access Control System

## Overview

A three-tier access control system simulating an NFC-based door entry solution, designed to demonstrate post-quantum-ready communication between IoT-class devices and cloud infrastructure. The system is a simulation/prototype: physical actuation (opening a lock) is stubbed and logged rather than performed.

**Components:**

1. **Access Reader**: edge device that simulates NFC key scans
2. **Edge Gateway**: stateless relay between readers and the cloud
3. **Cloud Server**: authoritative data store, access-event log, and admin control panel

All three are independently deployable Docker containers, orchestrated via `docker-compose.yml`. Multiple Access Readers can connect to one Edge Gateway; multiple Edge Gateways can connect to the Cloud Server.

---

## 1. Access Reader

**Role:** Driver of the simulated system. Generates key-scan events on a timer and requests an authorization decision for each.

**Behavior:**

- Runs as a Docker container.
- Periodically simulates a scan event: `{ "id": "<key_uuid>" }`.
- Sends the scanned key UUID, tagged with its own `reader_id`, to its configured Edge Gateway and awaits an authorization response.
- Logs the outcome (pass/fail) locally. (Simulates the outcome event)

**Configuration (per instance):**

- `READER_ID=<uuid>`: unique identifier for this reader.
- `ZONE=<zone_name>`: display label for the physical location (e.g. `front-door`, `server-room`). Used for logging/UI only; authorization is decided by `reader_id`, not by zone name.
- `GATEWAY=<ip:port>`: address of the Edge Gateway on the same VLAN.

**Network placement:** Reader VLAN, DHCP-assigned IP.

---

## 2. Edge Gateway

**Role:** Stateless relay.

**Behavior:**

- Receives an auth request (key UUID + reader_id) from a connected Access Reader.
- Forwards the request to the Cloud Server unchanged.
- Forwards the Cloud Server's response back to the requesting Access Reader.
- (Stretch goal, not required for MVP: cache recent responses for redundancy/performance if the Cloud Server is unreachable.)

**Configuration (per instance):**

- `CLOUD=<ip:port>`: address of the Cloud Server.
- `ID=<gateway_uuid>`: unique identifier for this gateway.

**Network placement:** Reader VLAN, static local IPv4 address.

---

## 3. Cloud Server

**Role:** Authoritative source of truth. Owns the relational database, evaluates authorization requests, logs all access events, and serves a simple admin control panel.

**Behavior:**

- Receives forwarded auth requests from Edge Gateways.
- Looks up whether the presented key UUID and the requesting reader_id share at least one group, and returns pass/fail. Authorization is decided per reader, not per gateway, so a gateway serving multiple zones can grant different access to each.
- Logs every access event: which key, which reader (and its zone), which gateway it came through, timestamp, and result.
- Serves a lightweight control panel (vanilla HTML/CSS/JS) showing: event logs, connected gateways, reader-to-gateway mappings with zone labels, and access history.

**Explicit non-goal:** The Cloud Server does **not** authenticate the identity of connecting gateways (no mutual TLS / gateway identity verification). This is an accepted, documented risk, not an oversight.

**Network placement:** Public internet, known public IP + DNS.

---

## Data Model (relational DB, implicit row IDs)

```sql
KEY_GROUPS(key_uuid, group_id);
READER_GROUPS(reader_id, group_id);
READERS(id, gateway_id, zone_name);
GROUPS(id);
GATEWAYS(id);
```

A key is authorized at a reader if they share at least one `group_id`. `zone_name` on `READERS` is a display label only; it plays no role in the authorization check. A gateway can serve readers in different zones with different group memberships, since authorization is keyed on `reader_id`, not `gateway_id`.

---

## Communication

| Hop | Protocol | Topology | Notes |
|---|---|---|---|
| Access Reader and Edge Gateway | TLS 1.3 (classical) | many-to-one | Same LAN; no post-quantum key exchange on this hop; payload includes reader_id and key_uuid |
| Edge Gateway and Cloud Server | TLS 1.3 + ML-KEM (hybrid PQC) | many-to-one | Crosses the public internet |
| Administrator to Cloud Server | HTTPS | n/a | Control panel access |

The asymmetry (classical crypto on the LAN hop, PQC-hybrid on the WAN hop) is intentional and should be discussed as a scope/risk decision.

---

## Assumptions & Explicit Scope Boundaries

- Physical access to the Reader VLAN is restricted by IT policy. Physical security itself is out of scope.
- Gateway -> Cloud Server authentication (proving a gateway is who it claims to be) is explicitly out of scope for this iteration.

---

## Deployment (docker-compose, indicative)

```yaml
services:
  reader-1:
    image: tbd:latest
    env:
      - READER_ID=<uuid>
      - ZONE=front-door
      - GATEWAY=ip:port
  # ... reader-N

  gateway-1:
    image: tbd:latest
    env:
      - CLOUD=ip:port
      - ID=<uuid>
  # ... gateway-N

  cloud:
    image: tbd:latest
    env:
      - <db config>
    volumes:
      - "./volumes/cloud/master.db:/path/master.db"

  sqlite-web:
    image: coleifer/sqlite-web:latest
    # mounts the same .db as cloud, for inspection
```
