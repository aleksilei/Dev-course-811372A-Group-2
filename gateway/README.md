# Edge Gateway

Run with `python -m gateway`. It's a stateless relay: WSS server for readers
(port 8765) and one persistent WSS client connection to the cloud.

## Configuration

| Variable | Default | |
|---|---|---|
| `CLOUD` | required | cloud address `host:port`, e.g. `cloud:8443` |
| `ID` | required | this gateway's ID, sent to the cloud as `Gateway-Id` |
| `PORT` | `8765` | port for readers |
| `TLS_CERT` / `TLS_KEY` | `/certs/server.pem` / `/certs/server.key` | certificate readers verify |
| `TLS_CA` | `/certs/ca.pem` | CA used to verify the cloud |
| `OPENSSL_CONF` | `/opt/lib/openssl/hybrid.cnf` (image) | key exchange with the cloud: hybrid `X25519MLKEM768` with `X25519` fallback; `hybrid-only.cnf` or `classical.cnf` instead, see [lib](../lib/README.md#gateway--cloud-ml-kem-hybrid-with-classical-fallback) |

## Behaviour

- **Reader side** (`readers.py`): readers connect with a `Reader-Id` header
  and are kept in memory while connected. Each message is forwarded to the
  cloud unchanged (only a `request_id` is added), and the reader gets back
  `{"result": "pass"}` or `{"result": "fail"}`.
- **Cloud side** (`cloud_link.py`): all readers share one connection, with
  post-quantum hybrid key exchange when the cloud supports it. Each
  forwarded request gets a unique `request_id`, and the cloud's reply is routed
  back to the waiting reader by that ID, so replies may arrive in any order.
  After a lost or failed connection it retries every 3 s.
- **Fails closed:** while the cloud is unreachable, when it doesn't answer
  within 5 s, or when the answer is anything but an explicit `pass`, the reader
  gets `fail`.
- No caching of cloud responses (a stretch goal in the spec).

```jsonc
// reader -> gateway
{"id": "key-bob", "reader_id": "rd-3"}
// gateway -> reader
{"result": "pass"}
```
