#!/usr/bin/env python3
"""Minimal bespoke PIN relay for the reachability experiment.

Accepts pin-clientd's REAL protocol (SSE downlink + signed HTTP uplinks)
and answers the handshake cycle locally, proving:
  1. inbound connections from the outside world reach this box
  2. pin-clientd completes the PIN auth handshake against the relay

Optionally forwards everything to the real gateway when FORWARD_TO is set,
but the default pure-local mode is what the reachability test needs.

Usage:
  python3 relay.py [--port 8080]

Mark's pin-clientd config points at it with:
  "server_url": "ws://<relay-host>:8080/api/v1/pin/ws",
  "transport": "sse"

(daemon maps ws:// -> http:// and strips the trailing /ws, so the SSE
connect becomes GET http://<host>:8080/api/v1/pin/stream/connect)

Stdlib only. Not for production.
"""

import argparse
import json
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORWARD_TO = None  # e.g. "https://aiassist.net" to proxy upstream

# token -> list of queued SSE event dicts
sessions = {}
sessions_lock = threading.Lock()


def queue_event(token, payload):
    with sessions_lock:
        sessions.setdefault(token, []).append(payload)


class Handler(BaseHTTPRequestHandler):
    server_version = "pin-relay/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.client_address[0]} {fmt % args}", flush=True)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _send(self, code, body=b"", ctype="application/json", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, b'{"ok":true}', extra=[("Connection", "close")])
        if self.path.endswith("/stream/connect"):
            return self._sse_connect()
        return self._send(404, b'{"error":"not found"}')

    def _sse_connect(self):
        client_id = self.headers.get("X-PIN-Client-Id", "?")
        ts = self.headers.get("X-PIN-Timestamp", "?")
        sig = (self.headers.get("X-PIN-Signature", "") or "")[:16]
        token = secrets.token_hex(16)
        print(f"[handshake] SSE connect client={client_id} ts={ts} sig={sig}... -> token={token}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-PIN-Stream-Token", token)
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(payload):
            data = json.dumps(payload, separators=(",", ":"))
            try:
                self.wfile.write(f"event: message\ndata: {data}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        emit({"type": "AUTH_SUCCESS", "operator_id": client_id,
              "node_id": None, "message": "pin-relay reachability test"})
        # keep stream open; drain queued ACKs for this session
        while True:
            with sessions_lock:
                queued = sessions.pop(token, [])
            for p in queued:
                emit(p)
            time.sleep(0.2)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        token = self.headers.get("X-PIN-Stream-Token", "?")
        body = self._body()
        kind = path.rsplit("/", 1)[-1] if "/stream/" in path else "?"

        if "/stream/" in path and kind in ("register", "heartbeat", "result", "chunk"):
            print(f"[uplink] {kind} token={token[:8] if token != '?' else '?'} "
                  f"bytes={len(body)}", flush=True)
            try:
                doc = json.loads(body) if body else {}
            except json.JSONDecodeError:
                doc = {}
            if kind == "register":
                queue_event(token, {
                    "type": "REGISTER_NODE_ACK",
                    "node_id": "relay-node-1",
                    "alias": doc.get("alias", "relay-node"),
                    "models": doc.get("models", []),
                    "created": True,
                    "message": "registered with pin-relay (test, not the real network)",
                })
            if FORWARD_TO:
                self._forward(path, body)
                return
            return self._send(200, b"{}", extra=[("Connection", "close")])

        return self._send(404, b'{"error":"not found"}')

    def _forward(self, path, body):
        url = FORWARD_TO + path
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={k: v for k, v in self.headers.items()})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                self._send(r.status, r.read(), r.headers.get_content_type())
        except Exception as e:  # noqa: BLE001
            self._send(502, json.dumps({"error": str(e)}).encode())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"pin-relay listening on 0.0.0.0:{args.port} "
          f"(forward={'off' if not FORWARD_TO else FORWARD_TO})", flush=True)
    srv.serve_forever()
