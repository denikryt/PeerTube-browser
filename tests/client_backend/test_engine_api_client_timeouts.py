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


def test_random_feed_uses_recommendations_timeout(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_post_json(url: str, payload: dict[str, object], timeout: int):
        calls.append((url, timeout))
        return 200, {"rows": []}

    monkeypatch.setattr(engine_api_client, "_post_json", fake_post_json)

    engine_api_client.fetch_engine_random("http://engine.local", limit=10)

    assert calls == [
        (
            "http://engine.local/recommendations?limit=10&random=1",
            engine_api_client.RECOMMENDATIONS_ENGINE_TIMEOUT_SECONDS,
        )
    ]
