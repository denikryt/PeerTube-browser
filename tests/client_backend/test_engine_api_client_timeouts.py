"""Engine API client timeout contract tests."""
from __future__ import annotations

from lib import engine_api_client


def test_recommendations_use_longer_engine_timeout(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_post_json(url: str, payload: dict[str, object], timeout: int):
        calls.append((url, timeout))
        return 200, {"rows": []}

    monkeypatch.setattr(engine_api_client, "_post_json", fake_post_json)

    engine_api_client.fetch_engine_recommendations(
        "http://engine.local",
        likes=[{"uuid": "u1", "host": "example.org"}],
        user_id="local-user",
        limit=21,
    )

    assert calls == [
        (
            "http://engine.local/recommendations?limit=21&user_id=local-user",
            engine_api_client.RECOMMENDATIONS_ENGINE_TIMEOUT_SECONDS,
        )
    ]
    assert engine_api_client.RECOMMENDATIONS_ENGINE_TIMEOUT_SECONDS > engine_api_client.DEFAULT_ENGINE_TIMEOUT_SECONDS


def test_paged_random_discovery_uses_normal_get_timeout(monkeypatch) -> None:
    """Paged Random uses the internal Discovery GET boundary, not recommendation POST."""
    calls: list[tuple[str, dict[str, object] | None, int]] = []

    def fake_get_json(url: str, query=None, timeout=engine_api_client.DEFAULT_ENGINE_TIMEOUT_SECONDS):
        calls.append((url, query, timeout))
        return 200, {"rows": [], "pagination": {"next_cursor": None, "has_more": False}}

    monkeypatch.setattr(engine_api_client, "_get_json", fake_get_json)
    engine_api_client.fetch_engine_discovery("http://engine.local", "random", 10, None, {})
    assert calls == [(
        "http://engine.local/internal/discovery/random",
        {"limit": 10},
        engine_api_client.DEFAULT_ENGINE_TIMEOUT_SECONDS,
    )]
