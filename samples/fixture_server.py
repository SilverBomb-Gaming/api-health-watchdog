#!/usr/bin/env python3
"""Local HTTP targets for the api-watch demo. The standard library only."""

from __future__ import annotations

import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class Handler(BaseHTTPRequestHandler):
    """Three routes: /ok (200), /fail (500), /slow (200 after 2 seconds)."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0]
        if path == "/ok":
            self._send(200, b"ok\n")
            return
        if path == "/fail":
            self._send(500, b"fail\n")
            return
        if path == "/slow":
            time.sleep(2)
            self._send(200, b"slow\n")
            return
        self._send(404, b"not found\n")

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"fixture server on http://{HOST}:{port}", flush=True)
    print("routes: /ok -> 200, /fail -> 500, /slow -> 200 after 2s", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
