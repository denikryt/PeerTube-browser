"""Shared FastAPI harnesses for Client backend characterization tests."""
from __future__ import annotations

import json
import socketserver
import sqlite3
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

RouteMap = dict[tuple[str, str], Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))

from app import create_app  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402
from repositories.users import UsersRepository  # noqa: E402
from runtime import ClientRuntimeState  # noqa: E402


class JsonFakeEngine(socketserver.ThreadingTCPServer):
    """Small fake Engine HTTP server that records requests and returns JSON."""

    allow_reuse_address = True

    def __init__(self, routes: RouteMap) -> None:
        """Start with explicit route handlers so tests define all upstream behavior."""
        super().__init__(("127.0.0.1", 0), _FakeEngineHandler)
        self.routes = routes
        self.requests: list[dict[str, Any]] = []

    @property
    def server_port(self) -> int:
        """Expose the chosen local port for Client proxy tests."""
        return int(self.server_address[1])


class _FakeEngineHandler(socketserver.StreamRequestHandler):
    """Minimal HTTP/1.1 JSON responder used as the Engine network boundary."""

    def handle(self) -> None:
        """Read one HTTP request, invoke the configured route, and write JSON."""
        request_line = self.rfile.readline().decode("iso-8859-1").strip()
        if not request_line:
            return
        method, target, _version = request_line.split(" ", 2)
        headers: dict[str, str] = {}
        while True:
            line = self.rfile.readline().decode("iso-8859-1")
            if line in {"\r\n", "\n", ""}:
                break
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length") or "0")
        raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            body = json.loads(raw_body) if raw_body.strip() else {}
        except json.JSONDecodeError:
            body = {}
        path = target.split("?", 1)[0]
        record = {"method": method, "path": path, "full_path": target, "body": body}
        self.server.requests.append(record)
        route = self.server.routes.get((method, path))
        if route is None:
            status, payload = 404, {"error": f"unhandled fake route {method} {path}"}
        else:
            status, payload = route(record)
        data = json.dumps(payload).encode("utf-8")
        reason = "OK" if status < 400 else "ERROR"
        headers_out = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "content-type: application/json; charset=utf-8\r\n"
            f"content-length: {len(data)}\r\n"
            "connection: close\r\n\r\n"
        ).encode("iso-8859-1")
        self.wfile.write(headers_out + data)


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

    def _start(routes: RouteMap) -> JsonFakeEngine:
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
    """Create a FastAPI TestClient around a temporary Client runtime state."""
    clients: list[TestClient] = []

    def _start(engine_base_url: str, publish_mode: str = "bridge") -> TestClient:
        state = ClientRuntimeState(
            user_db=client_db,
            users=UsersRepository(client_db),
            engine_ingest_base=engine_base_url,
            publish_mode=publish_mode,
            rate_limiter=RateLimiter(10_000, 60),
        )
        client = TestClient(create_app(state))
        clients.append(client)
        return client

    yield _start

    for client in clients:
        client.close()
