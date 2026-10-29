#!/usr/bin/env python
"""Fake memory server for the T02 hang test (runbook test B). Test use only.

It answers ``GET /health`` at once, so the Prismind instance under test
marks the memory backend available at start-up. Every other request gets a
200 header promising a large body, then one byte every ``--interval``
seconds, forever.

httpx's ``timeout=10.0`` bounds each read, not the whole response, so a
peer that keeps trickling bytes faster than that never times out. The
Prismind tool worker that made the request stays blocked, exactly as an
upstream that hangs this way would block it. Nothing in Prismind's own code
is changed to produce the hang.

    python deploy/hangtest/trickle_server.py --port 18080 --interval 5

Stop it with Ctrl-C (or kill the process) when the test is done.
"""

from __future__ import annotations

import argparse
import socketserver
import sys
import time
from http.server import BaseHTTPRequestHandler


class TrickleHandler(BaseHTTPRequestHandler):
    interval = 5.0
    protocol_version = "HTTP/1.1"

    def _trickle(self) -> None:
        if self.path.rstrip("/") == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        sys.stderr.write(f"trickling {self.command} {self.path}\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(10**9))
        self.end_headers()
        self.wfile.flush()
        try:
            while True:
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(self.interval)
        except (BrokenPipeError, ConnectionResetError):
            sys.stderr.write(f"client went away: {self.command} {self.path}\n")

    def _drain_body(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._trickle()

    def do_POST(self) -> None:  # noqa: N802
        self._drain_body()
        self._trickle()

    def do_PUT(self) -> None:  # noqa: N802
        self._drain_body()
        self._trickle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._trickle()


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--interval", type=float, default=5.0,
        help="Seconds between bytes. Keep it under the client's read timeout (10s).",
    )
    args = parser.parse_args(argv)

    TrickleHandler.interval = args.interval
    with Server((args.host, args.port), TrickleHandler) as server:
        sys.stderr.write(f"trickle server on http://{args.host}:{args.port}\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
