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
| `KEY_EXCHANGE` | `hybrid` | key exchange with the cloud: `hybrid` (`X25519MLKEM768` with `X25519` fallback), `hybrid-only` or `classical`; anything else, or a leftover `OPENSSL_CONF`, stops the gateway at startup. See [lib](../lib/README.md#gateway--cloud-ml-kem-hybrid-with-classical-fallback) |

## Behaviour

- **Reader side** (`readers.py`): readers connect with a `Reader-Id` header
  and are kept in memory while connected. Each message is forwarded to the
  cloud unchanged (only a `request_id` is added), and the reader gets back
  `{"result": "pass"}` or `{"result": "fail"}`.
- **Cloud side** (`cloud_link.py`): all readers share one connection, with
  post-quantum hybrid key exchange when the cloud supports it. The handshake
  sends `Gateway-Id` and the gateway's own `OpenSSL-Version`. Each
  forwarded request gets a unique `request_id`, and the cloud's reply is routed
  back to the waiting reader by that ID, so replies may arrive in any order.
  After a lost or failed connection it retries every 3 s.
- **Connected readers:** the gateway tells the cloud which readers are
  connected to it (ID, address, connected since, the TLS version, cipher
  suite and key exchange of its connection, and the OpenSSL version it
  reported in its `OpenSSL-Version` header) whenever one
  connects or disconnects, and again after every reconnect to the cloud. Only
  the latest list is sent. A cloud from before this feature answers `fail`,
  which is only logged. The control panel shows the lists.
- **Fails closed:** while the cloud is unreachable, when it doesn't answer
  within 5 s, or when the answer is anything but an explicit `pass`, the reader
  gets `fail`. Requests in flight when the cloud connection drops fail at
  once.
- No caching of cloud responses (a stretch goal in the spec).

```jsonc
// reader -> gateway
{"id": "key-bob", "reader_id": "rd-3"}
// gateway -> reader
{"result": "pass"}
// gateway -> cloud, on every change in its connected readers
{"type": "readers", "request_id": "…", "readers": [
  {"id": "rd-3", "address": "10.10.0.4", "since": "2026-11-15T12:00:00+00:00",
   "tls_version": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384", "key_exchange": "X25519"}
]}
// cloud -> gateway
{"request_id": "…", "result": "ok"}
```
