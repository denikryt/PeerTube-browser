"""FastAPI contract tests for the Engine API adapter."""
from __future__ import annotations

import sqlite3
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))
for module_name in ("app", "runtime", "http_adapters"):
    sys.modules.pop(module_name, None)
fake_ann = types.ModuleType("data.ann")
fake_ann.search_index = lambda *_args, **_kwargs: ([], [])
sys.modules["data.ann"] = fake_ann

import app as engine_app  # noqa: E402
from app import create_app  # noqa: E402
from http_utils import RateLimiter  # noqa: E402
from runtime import EngineRuntimeState  # noqa: E402


def make_state() -> EngineRuntimeState:
    """Create a minimal Engine runtime state for FastAPI adapter tests."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return EngineRuntimeState(
        db=conn,
        similarity_db=None,
        random_cache_db=None,
        index=None,
        embeddings_dim=384,
        embeddings_count=7,
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
        rate_limiter=RateLimiter(10_000, 60),
        popularity_like_weight=1.0,
        enable_instance_ignore=True,
        enable_channel_blocklist=True,
        engine_ingest_mode="disabled",
        db_lock=threading.Lock(),
        similarity_db_lock=threading.Lock(),
        random_cache_lock=threading.Lock(),
        index_lock=threading.Lock(),
    )


def test_engine_fastapi_health_options_and_unknown_route() -> None:
    """Engine FastAPI health, CORS, and unknown-route contracts stay stable."""
    state = make_state()
    client = TestClient(create_app(state))

    health = client.get("/api/health")
    options = client.options("/api/health")
    missing = client.get("/missing")

    assert health.status_code == 200
    assert health.json() == {"ok": True, "total": 7, "embeddingDim": 384}
    assert options.status_code == 204
    assert options.headers["access-control-allow-origin"] == "*"
    assert missing.status_code == 404
    assert missing.json() == {"error": "Not found"}


def test_engine_fastapi_rate_limit_key_and_status() -> None:
    """Engine FastAPI adapter keeps the current rate-limit body and status."""
    state = make_state()
    state.rate_limiter = RateLimiter(1, 60)
    client = TestClient(create_app(state))

    first = client.get("/api/health")
    second = client.get("/api/health")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {"error": "Rate limit exceeded"}


def test_engine_fastapi_internal_events_disabled_gate() -> None:
    """Internal event ingest keeps the current disabled-mode 501 payload."""
    state = make_state()
    state.engine_ingest_mode = "activitypub"
    client = TestClient(create_app(state))

    response = client.post("/internal/events/ingest", json={"event_id": "evt-1"})

    assert response.status_code == 501
    assert response.json() == {
        "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
        "mode": "activitypub",
    }


def test_engine_fastapi_similar_path_injects_id(monkeypatch) -> None:
    """Path-based similar route keeps injecting the path id before delegation."""
    state = make_state()
    captured: dict[str, Any] = {}

    def fake_handle(handler: Any, server: Any, path: str, params: dict[str, list[str]]) -> bool:
        """Capture the params received after path-id injection."""
        captured["path"] = path
        captured["params"] = params
        from http_utils import respond_json

        respond_json(handler, 200, {"rows": [], "count": 0})
        return True

    monkeypatch.setattr(engine_app, "handle_similar_get", fake_handle)
    client = TestClient(create_app(state))

    response = client.get("/videos/abc-123/similar?limit=5")

    assert response.status_code == 200
    assert captured["path"] == "/videos/abc-123/similar"
    assert captured["params"]["id"] == ["abc-123"]
    assert captured["params"]["limit"] == ["5"]


def test_engine_fastapi_internal_video_routes_delegate(monkeypatch) -> None:
    """Internal video resolve and metadata routes use the existing adapters."""
    state = make_state()

    def fake_resolve(handler: Any, server: Any) -> bool:
        """Return a known resolve payload through the handler response path."""
        from http_utils import respond_json

        respond_json(handler, 200, {"video": {"video_id": "123"}})
        return True

    def fake_metadata(handler: Any, server: Any) -> bool:
        """Return a known metadata payload through the handler response path."""
        from http_utils import respond_json

        respond_json(handler, 200, {"rows": [{"video_id": "123"}]})
        return True

    monkeypatch.setattr(engine_app, "handle_internal_video_resolve_route", fake_resolve)
    monkeypatch.setattr(engine_app, "handle_internal_videos_metadata_route", fake_metadata)
    client = TestClient(create_app(state))

    resolve = client.post("/internal/videos/resolve", json={"uuid": "uuid"})
    metadata = client.post("/internal/videos/metadata", json={"videos": []})

    assert resolve.status_code == 200
    assert resolve.json() == {"video": {"video_id": "123"}}
    assert metadata.status_code == 200
    assert metadata.json() == {"rows": [{"video_id": "123"}]}
