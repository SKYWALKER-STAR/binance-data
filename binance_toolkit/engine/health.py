"""Lightweight health and metrics HTTP server for strategy engine."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


class EngineHealthServer:
    """Expose /health and /metrics using stdlib http server."""

    def __init__(self, host: str, port: int, snapshot_provider: Callable[[], dict]):
        self._host = host
        self._port = port
        self._snapshot_provider = snapshot_provider
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._port <= 0:
            return

        snapshot_provider = self._snapshot_provider

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                snapshot = snapshot_provider()
                if self.path == "/health":
                    body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/metrics":
                    metrics = snapshot.get("metrics", {})
                    lines = [f"binance_engine_{name} {value}" for name, value in metrics.items()]
                    body = ("\n".join(lines) + "\n").encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="engine-health")
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None
