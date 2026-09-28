# Access Reader

Run with `python -m reader`. Every `SCAN_INTERVAL` seconds it "scans" a random
key from `KEYS`, asks its gateway for a decision, and logs the outcome. On a
pass it calls the `unlock()` stub, which only logs.

## Configuration

| Variable | Default | |
|---|---|---|
| `READER_ID` | required | e.g. `rd-1`, must exist in the cloud's `READERS` table to ever pass |
| `ZONE` | required | display label for the logs only |
| `GATEWAY` | required | gateway address `host:port`, e.g. `10.10.0.10:8765` |
| `KEYS` | `key-alice,key-bob,key-carol,key-mallory` | keys to pick from (`key-mallory` is unknown and always fails) |
| `SCAN_INTERVAL` | `5` | seconds between scans |
| `TLS_CA` | `/certs/ca.pem` | CA used to verify the gateway |

## Behaviour

- Connects to `wss://GATEWAY` with a `Reader-Id` handshake header on the first
  scan and keeps the connection open between scans.
- **Fails closed:** if the gateway is unreachable or doesn't answer within 5 s,
  the scan is a `FAIL` and the connection is dropped. The next scan reconnects.
- Log line per scan, e.g.
  `PASS key=key-bob reader=rd-3 zone=server-room`, then `UNLOCK server-room (stub, ...)`.
