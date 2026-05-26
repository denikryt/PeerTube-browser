"""Shared Engine API characterization test helpers."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import threading
import types
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
for module_name in ("app", "runtime", "http_adapters"):
    sys.modules.pop(module_name, None)
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

fake_ann = types.ModuleType("data.ann")
fake_ann.search_index = lambda *_args, **_kwargs: ([], [])
sys.modules.setdefault("data.ann", fake_ann)

from app import create_app  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema  # noqa: E402
from runtime import EngineRuntimeState  # noqa: E402


class CapturingHandler:
    """Structural handler harness for direct route/service tests."""

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


class RejectingRateLimiter:
    """Rate limiter fake that rejects all requests and records the requested key."""

    def __init__(self) -> None:
        """Initialize the fake with no recorded key."""
        self.key: str | None = None

    def allow(self, key: str) -> bool:
        """Reject the request while preserving the current rate-limit key."""
        self.key = key
        return False


def make_engine_state(**overrides: Any) -> EngineRuntimeState:
    """Create a minimal Engine runtime state for FastAPI route tests."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    state = EngineRuntimeState(
        db=conn,
        similarity_db=None,
        random_cache_db=None,
        index=None,
        embeddings_dim=384,
        embeddings_count=42,
        default_limit=100,
        normalize_queries=True,
        refresh_similarity_cache=False,
        similarity_require_full_cache=False,
        similarity_allow_ann_on_cache_miss=True,
        similarity_search_limit=100,
        similarity_max_per_author=3,
        similarity_exclude_source_author=True,
        recommendation_strategy=SimpleNamespace(name="test"),
        related_personalization_deps=None,
        related_personalization_enabled=False,
        video_error_threshold=3,
        recommendations_debug_enabled=False,
        use_client_likes=True,
        rate_limiter=None,
        popularity_like_weight=1.0,
        enable_instance_ignore=True,
        enable_channel_blocklist=True,
        engine_ingest_mode="disabled",
        db_lock=threading.RLock(),
        similarity_db_lock=threading.RLock(),
        random_cache_lock=threading.RLock(),
        index_lock=threading.RLock(),
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


@pytest.fixture
def engine_state() -> EngineRuntimeState:
    """Provide a minimal Engine runtime state and close its DB after use."""
    state = make_engine_state()
    yield state
    state.db.close()


@pytest.fixture
def engine_client(engine_state: EngineRuntimeState) -> TestClient:
    """Provide a FastAPI TestClient for Engine route characterization tests."""
    with TestClient(create_app(engine_state)) as client:
        yield client
