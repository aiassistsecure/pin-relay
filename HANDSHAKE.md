# PIN wire protocol — handshake details for the relay experiment

Extracted 2026-10-04 from `pin-clientd` v2.3.0
(repo aiassistsecure/pin-clientd, commit be51571, files src/main.rs + src/sse.rs).

These are the exact details the relay needs to speak the REAL protocol —
no invented handshake, per Mark's direction ("reuse the existing p2p
protocol and handshake through a bespoke proxy").

## Transports

Default server URL: `wss://aiassist.net/api/v1/pin/ws`. Default transport
is now `sse` (config key `transport`: `"sse"` or `"ws"`; WebSocket stays as
compatibility fallback).

Both are configured with two config keys:
- `server_url` — any URL works, this is how the daemon gets pointed at a relay
- `transport` — `"sse"` or `"ws"`

## SSE transport (the live operator path)

1. `GET {http_base}/stream/connect` where
   `http_base = server_url` minus trailing `/ws`, with `wss://`→`https://`
   (and `ws://`→`http://`).
   Headers (required):
   - `X-PIN-Client-Id: op_...` (operator id)
   - `X-PIN-Timestamp: <unix epoch seconds>`
   - `X-PIN-Signature: <signature>`
   - `Accept: text/event-stream`
2. The server MUST reply 200 **and** include an `X-PIN-Stream-Token`
   response header. The daemon errors out if it is missing
   ("SSE response missing X-PIN-Stream-Token").
3. The downlink is a persistent SSE stream. Frames are JSON with a
   `"type"` tag. The first thing the daemon expects is:
   `{"type":"AUTH_SUCCESS","operator_id":"op_...","node_id":null,"message":"..."}`

### Signature (identical for SSE headers and the WS AUTH frame)

```
secret_hash = sha256hex(api_secret)
signature   = sha256hex(client_id + timestamp + secret_hash)
```
(double sha256 — secret is hashed first, then concatenated
client_id || timestamp || secret_hash-hex)

### Uplinks (independent POSTs, not on the SSE stream)

`POST {http_base}/stream/{path}` with the same signature headers plus
`X-PIN-Stream-Token: <token>`:
- `heartbeat` — body empty `{}`; server should also accept the
  `X-PIN-Models` request header
- `register` — body: `{alias, models[], capacity, region,
  pricePerThousandTokens, interviewModel?, apiMode}` (camelCase);
  server answers 200 and should push
  `REGISTER_NODE_ACK {node_id, alias, models[], created, message}`
  down the SSE stream
- `result` — inference result (body carries request_id + result)
- `chunk` — `INFERENCE_CHUNK {type, request_id, index, delta}` frames

Other downlink frame types the daemon understands (for completeness):
PING, HEARTBEAT_ACK, MODEL_LIST_ACK, RESULT_ACK, INFERENCE_REQUEST
{request_id, payload}, CANCEL_REQUEST {request_id}, TTS_REQUEST,
INTERVIEW_REQUEST / INTERVIEW_RESULT / INTERVIEW_COMPLETE /
INTERVIEW_FAILED, ERROR, UPDATE_WALLET_ACK.

## WebSocket fallback

1. Connect to `server_url` directly, e.g. `wss://aiassist.net/api/v1/pin/ws`.
2. Send a text frame: `{"type":"AUTH","client_id":"op_...","timestamp":"...","signature":"..."}` (same signature formula).
3. Expect `AUTH_SUCCESS`, then the daemon sends
   `{"type":"REGISTER_NODE", ...}` with the node config.

## Pointing Mark's daemon at the relay

In his config.json:

```json
{
  "clientId": "op_...",
  "apiSecret": "pin_sk_...",
  "server_url": "ws://<relay-host>:8080/api/v1/pin/ws",
  "transport": "sse",
  "nodes": [ { "alias": "Relay-Test", "inferenceUri": "http://localhost:11434", "apiMode": "ollama", "region": "us-east", "capacity": 1 } ]
}
```

Note: with `transport: sse`, the daemon connects to
`http://<relay-host>:8080/api/v1/pin/stream/connect` (the `/ws` suffix is
stripped and `ws://` becomes `http://`). Use plain `ws://` for a first
cleartext test; move to TLS (`wss://`) once reachability is proven.

## The relay implementation in this folder

`relay.py` (stdlib only) implements exactly the above:
- `GET /api/v1/pin/stream/connect` → 200 + X-PIN-Stream-Token + SSE stream
  that immediately emits AUTH_SUCCESS (accepts any signature — reachability,
  not auth, is what the test proves)
- `POST /stream/register|heartbeat|result|chunk` → 200; register pushes
  REGISTER_NODE_ACK onto that client's stream
- `GET /health` → 200, for a quick `curl` reachability ping before
  running the daemon

Run: `python3 relay.py --port 8080` (binds 0.0.0.0).

## Open questions for the real test

1. Inbound reachability: does the box the relay runs on accept connections
   from the outside world? (the thing the experiment exists to find out)
2. Mark runs the daemon from his side pointed at the relay URL.
3. TLS for a real-world proxy comes later; the first test can be cleartext.
