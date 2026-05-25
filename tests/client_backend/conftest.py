"""Shared harnesses for Client backend HTTP characterization tests."""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))

from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402
from server import ClientBackendHandler, ClientBackendServer  # noqa: E402


class JsonFakeEngine(ThreadingHTTPServer):
    """Small fake Engine server that records requests and returns route handlers."""

    def __init__(self, routes: dict[tuple[str, str], Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]]) -> None:
        """Start with explicit route handlers so tests define all upstream behavior."""
        super().__init__(("127.0.0.1", 0), _FakeEngineHandler)
        self.routes = routes
        self.requests: list[dict[str, Any]] = []


class _FakeEngineHandler(BaseHTTPRequestHandler):
    """HTTP handler used by JsonFakeEngine to emulate Engine JSON routes."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress noisy test server access logs."""
        return

    def do_GET(self) -> None:  # noqa: N802
        """Record GET requests and return a configured JSON response."""
        self._handle({})

    def do_POST(self) -> None:  # noqa: N802
        """Record POST JSON bodies and return a configured JSON response."""
        length = int(self.headers.get("content-length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            body = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            body = {}
        self._handle(body)

    def _handle(self, body: dict[str, Any]) -> None:
        """Resolve the configured route and write a JSON response."""
        path = self.path.split("?", 1)[0]
        record = {"method": self.command, "path": path, "full_path": self.path, "body": body}
        self.server.requests.append(record)
        route = self.server.routes.get((self.command, path))
        if route is None:
            status, payload = 404, {"error": f"unhandled fake route {self.command} {path}"}
        else:
            status, payload = route(record)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def client_db() -> sqlite3.Connection:
    """Provide a Client users DB with production schema in a temporary database."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ensure_user_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def start_json_engine():
    """Start a fake Engine server and clean it up after the test."""
    servers: list[JsonFakeEngine] = []

    def _start(routes: dict[tuple[str, str], Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]]) -> JsonFakeEngine:
        server = JsonFakeEngine(routes)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return server

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def start_client_backend(client_db: sqlite3.Connection):
    """Start the real Client backend handler around a temporary users DB."""
    servers: list[ClientBackendServer] = []

    def _start(engine_base_url: str, publish_mode: str = "bridge") -> ClientBackendServer:
        server = ClientBackendServer(
            ("127.0.0.1", 0),
            ClientBackendHandler,
            client_db,
            engine_base_url,
            publish_mode,
            RateLimiter(10_000, 60),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return server

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()


def request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Send a JSON request and return status/body without hiding HTTP errors."""
    data = json.dumps(payload or {}).encode("utf-8") if method == "POST" else None
    request = Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body else {}
    except Exception as exc:
        from urllib.error import HTTPError

        if isinstance(exc, HTTPError):
            body = exc.read().decode("utf-8")
            return int(exc.code), json.loads(body) if body else {}
        raise


@pytest.fixture
def http_json():
    """Expose the JSON request helper as a fixture for HTTP scenario tests."""
    return request_json
