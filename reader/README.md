# Access Reader

Run with `python -m reader`. It "scans" a random key from `KEYS`, asks its
gateway for a decision, logs the outcome, waits a random time between
`SCAN_INTERVAL_MIN` and `SCAN_INTERVAL_MAX` seconds, and repeats. On a pass it
calls the `unlock()` stub, which only logs.

## Configuration

| Variable | Default | |
|---|---|---|
| `READER_ID` | required | e.g. `rd-1`, must exist in the cloud's `READERS` table to ever pass |
| `ZONE` | required | display label for the logs only |
| `GATEWAY` | required | gateway address `host:port`, e.g. `10.10.0.10:8765` |
| `KEYS` | `key-alice,key-bob,key-carol,key-mallory` | keys to pick from (`key-mallory` is unknown and always fails) |
| `SCAN_INTERVAL_MIN` | `2` | shortest wait between scans, in seconds |
| `SCAN_INTERVAL_MAX` | `8` | longest wait between scans, in seconds |
| `SCAN_INTERVAL` | unset | a fixed wait instead of the random one (the e2e tests use `1`) |
| `TLS_CA` | `/certs/ca.pem` | CA used to verify the gateway |

## Scan interval

- Each wait is drawn anew, uniformly from the range, so readers fall out of
  step and some make more traffic than others. The default 2-8 s averages the
  5 s of the old fixed interval.
- `SCAN_INTERVAL` alone means `SCAN_INTERVAL_MIN = SCAN_INTERVAL_MAX`; setting
  it together with either of those is an error. Empty values count as unset,
  since `docker-compose.yml` passes unset variables as empty strings.
- The reader stops at startup on a value that is not a number, negative or
  infinite, a minimum above the maximum, or a range of only 0 s.
- `make run-scaled` gives each site its own range: busy (1-3 s), normal
  (2-8 s), quiet (5-15 s) and very quiet (10-30 s) in turn.

## Behaviour

- Connects to `wss://GATEWAY` with a `Reader-Id` handshake header on the first
  scan and keeps the connection open between scans.
- **Fails closed:** if the gateway is unreachable or doesn't answer within 5 s,
  the scan is a `FAIL` and the connection is dropped. The next scan reconnects.
- Log line per scan, e.g.
  `PASS key=key-bob reader=rd-3 zone=server-room`, then `UNLOCK server-room (stub, ...)`.
