#!/usr/bin/env python3
"""Local-only reverse proxy for Tailscale Serve -> Hermes Dashboard.

Hermes Dashboard intentionally rejects non-local Host headers because it exposes
sensitive config. Tailscale Serve preserves the public tailnet hostname in Host,
so this tiny proxy rewrites Host back to 127.0.0.1:9119 while remaining bound to
127.0.0.1 only. Tailscale Serve then exposes this proxy inside the tailnet.
"""
from __future__ import annotations

import http.client
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 9119
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9120

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() != "host"
        }
        headers["Host"] = f"{BACKEND_HOST}:{BACKEND_PORT}"
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "https"

        conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=30)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()

            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                # We recalculate Content-Length after reading the full response.
                if k.lower() not in HOP_BY_HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)
        except Exception as exc:
            msg = f"Hermes dashboard proxy error: {exc}\n".encode()
            self.send_response(502, "Bad Gateway")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
        finally:
            conn.close()

    def do_GET(self): self._proxy()
    def do_POST(self): self._proxy()
    def do_PUT(self): self._proxy()
    def do_PATCH(self): self._proxy()
    def do_DELETE(self): self._proxy()
    def do_OPTIONS(self): self._proxy()
    def do_HEAD(self): self._proxy()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))

if __name__ == "__main__":
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Proxy)
    print(f"Hermes dashboard tailnet proxy listening on http://{LISTEN_HOST}:{LISTEN_PORT} -> http://{BACKEND_HOST}:{BACKEND_PORT}", flush=True)
    server.serve_forever()
