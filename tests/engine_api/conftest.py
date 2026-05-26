"""Shared Engine API characterization test helpers."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import threading
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.interaction_events import ensure_interaction_event_schema  # noqa: E402


class CapturingHandler:
    """Minimal BaseHTTPRequestHandler-like object for direct handler tests."""

    def __init__(self, body: dict[str, Any] | None = None) -> None:
        """Encode the request body and prepare response capture fields."""
        raw = json.dumps(body or {}).encode("utf-8")
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.headers = Message()
        self.headers["content-length"] = str(len(raw))
        self.status: int | None = None
        self.response_headers: list[tuple[str, str]] = []
        self.response_body: dict[str, Any] | None = None

    def send_response(self, status: int) -> None:
        """Capture HTTP status sent by respond_json."""
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        """Capture response headers without enforcing header semantics."""
        self.response_headers.append((key, value))

    def end_headers(self) -> None:
        """Keep compatibility with respond_json."""
        return

    def parsed_body(self) -> dict[str, Any]:
        """Decode the JSON body written by the handler."""
        self.wfile.seek(0)
        data = self.wfile.read().decode("utf-8")
        self.response_body = json.loads(data) if data else {}
        return self.response_body


@pytest.fixture
def engine_event_server() -> SimpleNamespace:
    """Provide the server attributes required by internal event ingest handler."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ensure_interaction_event_schema(conn)
    server = SimpleNamespace(db=conn, db_lock=threading.RLock())
    yield server
    conn.close()


def install_fake_ann(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a minimal fake ANN module so Engine route tests avoid FAISS."""
    import types

    fake_ann = types.ModuleType("data.ann")
    fake_ann.search_index = lambda *_args, **_kwargs: ([], [])
    monkeypatch.setitem(sys.modules, "data.ann", fake_ann)


def import_similar_handler_module(monkeypatch: pytest.MonkeyPatch):
    """Import ``handlers.similar`` with only heavyweight ANN access faked."""
    import importlib

    install_fake_ann(monkeypatch)
    for name in list(sys.modules):
        if (
            name == "handlers.similar"
            or name.startswith("routes.")
            or name.startswith("engine.server.api.routes.")
        ):
            sys.modules.pop(name, None)
    return importlib.import_module("handlers.similar")


class RouteCapturingHandler(CapturingHandler):
    """BaseHTTPRequestHandler-like harness for exercising SimilarHandler routes."""

    def __init__(
        self,
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        server: Any | None = None,
    ) -> None:
        """Prepare route, request metadata, server state, and response capture."""
        super().__init__(body)
        self.path = path
        self.command = method
        self.server = server if server is not None else SimpleNamespace(rate_limiter=None)
        self.client_address = ("127.0.0.1", 12345)
        self.headers["Host"] = "engine.local"

    def _get_client_ip(self) -> str:
        """Return the test client IP using the production handler contract."""
        return self.client_address[0] if self.client_address else "unknown"

    def _get_full_url(self) -> str:
        """Build a simple absolute URL for access-log compatibility."""
        return f"http://engine.local{self.path}"

    def _log_access_start(self) -> None:
        """No-op request-start hook for route dispatch tests."""
        return

    def _rate_limit_check(self, path: str) -> bool:
        """Use the production rate-limit key shape in handler tests."""
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None:
            return True
        return limiter.allow(f"{self._get_client_ip()}:{path}")


class RejectingRateLimiter:
    """Rate limiter fake that rejects all requests and records the requested key."""

    def __init__(self) -> None:
        """Initialize the fake with no recorded key."""
        self.key: str | None = None

    def allow(self, key: str) -> bool:
        """Reject the request while preserving the current rate-limit key."""
        self.key = key
        return False
