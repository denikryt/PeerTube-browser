"""Engine internal video search route behavior tests."""
from __future__ import annotations

from engine.server.data.video_search import rebuild_video_search_index


def _install_schema(conn) -> None:
    """Create a compact Engine runtime schema for internal search tests."""
    conn.executescript(
        """
        CREATE TABLE channels (channel_id TEXT, display_name TEXT, avatar_url TEXT, instance_domain TEXT, PRIMARY KEY(channel_id, instance_domain));
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT, channel_id TEXT,
          channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT,
          tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT,
          embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER,
          preview_path TEXT, popularity REAL DEFAULT 0, invalid_reason TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        """
    )
    conn.executemany(
        "INSERT INTO videos(video_id, video_uuid, instance_domain, channel_id, channel_name, title, tags_json, category, published_at, popularity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("a", "ua", "one.example", "c1", "Linux", "Linux alpha", '["tag"]', "Tech", 100, 3),
            ("b", "ub", "one.example", "c1", "Linux", "Linux beta", '["tag"]', "Tech", 200, 2),
            ("c", "uc", "one.example", "c1", "Linux", "Linux gamma", '["tag"]', "Tech", 300, 1),
        ],
    )


def test_internal_search_returns_provider_envelope(engine_client, engine_state) -> None:
    """Internal route returns rows and provider pagination without exposing FTS rowids."""
    _install_schema(engine_state.db)
    rebuild_video_search_index(engine_state.db)
    response = engine_client.get("/internal/search/videos?q=linux&limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 2
    assert payload["has_more"] is True
    assert payload["next_cursor"]
    assert [row["video_id"] for row in payload["rows"]] == ["a", "b"]
    assert "doc_id" not in payload["rows"][0]
    page2 = engine_client.get(f"/internal/search/videos?q=linux&limit=2&cursor={payload['next_cursor']}")
    assert page2.status_code == 200
    assert [row["video_id"] for row in page2.json()["rows"]] == ["c"]


def test_internal_search_rejects_empty_q_and_clamps_limit(engine_client, engine_state) -> None:
    """Validation catches empty q and clamps excessive limits at the provider edge."""
    _install_schema(engine_state.db)
    rebuild_video_search_index(engine_state.db)
    assert engine_client.get("/internal/search/videos?q=%20%20").status_code == 400
    response = engine_client.get("/internal/search/videos?q=linux&limit=999")
    assert response.status_code == 200
    assert response.json()["limit"] == 50


def test_internal_search_missing_index_is_controlled_503(engine_client, engine_state) -> None:
    """Unbuilt FTS index state returns a controlled provider error."""
    _install_schema(engine_state.db)
    response = engine_client.get("/internal/search/videos?q=linux")
    assert response.status_code == 503
    assert "Video search index unavailable" in response.json()["error"]
