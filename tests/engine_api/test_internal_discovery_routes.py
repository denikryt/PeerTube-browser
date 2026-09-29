"""Engine internal discovery provider route tests."""
from __future__ import annotations


def _prepare_db(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT, PRIMARY KEY(channel_id, instance_domain));
        CREATE TABLE interaction_signals (video_uuid TEXT, instance_domain TEXT, likes_count INTEGER DEFAULT 0, undo_likes_count INTEGER DEFAULT 0, signal_score REAL DEFAULT 0, PRIMARY KEY(video_uuid, instance_domain));
        CREATE TABLE instance_denylist (host TEXT PRIMARY KEY, is_active INTEGER, reason TEXT, note TEXT, created_at INTEGER, updated_at INTEGER);
        CREATE TABLE channel_moderation (channel_id TEXT, instance_domain TEXT, status TEXT, reason TEXT, source_video_url TEXT, updated_at INTEGER, created_at INTEGER, PRIMARY KEY(channel_id, instance_domain));
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT, channel_id TEXT,
          channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT,
          tags_json TEXT, category TEXT, category_id TEXT, language TEXT, language_label TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, thumbnail_candidates_json TEXT,
          embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER,
          preview_path TEXT, popularity REAL, last_checked_at INTEGER, error_count INTEGER DEFAULT 0, invalid_reason TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY(video_id, instance_domain));
        """
    )
    conn.execute("INSERT OR IGNORE INTO channels VALUES ('c', 'example.org', 'Channel', '/avatar.png')")
    for video_id, published, popularity in [("old", 1000, 1.0), ("new", 3000, 2.0), ("popular", 2000, 50.0)]:
        conn.execute(
            """
            INSERT INTO videos VALUES (?, ?, ?, 'example.org', 'c', 'c', 'https://example.org/c/c', 'acct',
            'https://example.org/a/acct', ?, 'desc', '[]', 'cat', '1', 'en', 'English', ?, 'https://example.org/w/x', 60,
            '/thumb.jpg', NULL, '/embed', 10, 1, 0, 0, 0, '/preview.jpg', ?, 1000, 0, NULL)
            """,
            (video_id, f"uuid-{video_id}", len(video_id), f"Title {video_id}", published, popularity),
        )
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'example.org', 3, 'test')", (video_id,))
    conn.commit()


def test_internal_fresh_provider_returns_recent_rows(engine_state, engine_client) -> None:
    _prepare_db(engine_state.db)

    response = engine_client.get("/internal/discovery/fresh?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fresh"
    assert [row["video_id"] for row in body["rows"]] == ["new", "popular"]


def test_internal_popular_provider_returns_popular_rows(engine_state, engine_client) -> None:
    _prepare_db(engine_state.db)

    response = engine_client.get("/internal/discovery/popular?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "popular"
    assert [row["video_id"] for row in body["rows"]] == ["popular", "new"]
