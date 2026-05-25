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
