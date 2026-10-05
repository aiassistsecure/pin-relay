# pin-relay

Lightweight relay/proxy for the **PIN (p2p inference network)** reachability
experiment.

## What it is

A small Python relay that speaks the real `pin-clientd` handshake protocol —
extracted from the daemon's source, not invented. It exists for one purpose:
testing whether a PIN node on the outside world can reach a relay through
inbound connections and complete the handshake.

## How the experiment works

1. Run `relay.py` somewhere publicly reachable.
2. Point a PIN node's `server_url` at the relay's public URL.
3. The node pings from the outside world; the relay proxies the handshake
   through to the real PIN protocol.

See [HANDSHAKE.md](HANDSHAKE.md) for the exact wire protocol: SSE connect,
signature headers, stream-token flow, and the uplink paths
(heartbeat / register / result / chunk).

## Running it

```sh
python3 relay.py
```

The relay also exposes `/health` for a quick reachability ping.

## Caveat

The relay accepts any signature in test mode — it proves reachability and
protocol compatibility, not auth.
