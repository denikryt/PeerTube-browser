"""Route-level video-availability matrix through real Engine dispatch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from handlers import video

from engine.server.data.prepared_discovery import rebuild_prepared_discovery
from engine.server.data.video_search import rebuild_video_search_index
from engine.server.db.bootstrap import bootstrap_engine_runtime_db
from engine.server.db.migrations.apply import apply_video_index_ids_migration

ROOT = Path(__file__).resolve().parents[2]


def _seed(conn):
    """Create the real crawler/canonical schema and all matrix identities/artifacts."""
    conn.executescript((ROOT / "engine/crawler/schema.sql").read_text())
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL DEFAULT 0")
    bootstrap_engine_runtime_db(conn)
    apply_video_index_ids_migration(conn)
    conn.execute("""CREATE TABLE video_embeddings(video_id TEXT,instance_domain TEXT,
        embedding BLOB,embedding_dim INTEGER,model_name TEXT,created_at TEXT,
        PRIMARY KEY(video_id,instance_domain))""")
    conn.execute(
        "INSERT INTO channels(channel_id,instance_domain,channel_name) "
        "VALUES('c','example.org','channel')"
    )
    for index, reason in enumerate([None, "not_found", "gone", "legacy_unknown", "", None]):
        conn.execute(
            """INSERT INTO videos(video_id,video_uuid,instance_domain,channel_id,title,
            tags_json,last_checked_at,invalid_reason,error_count)
            VALUES(?,?,'example.org','c','availabilityword','["linux"]',1,?,?)""",
            (str(index), f"uuid-{index}", reason, 10 if index == 5 else 0),
        )
        conn.execute(
            """INSERT INTO video_embeddings(video_id,instance_domain,embedding,
            embedding_dim,model_name,created_at) VALUES(?,'example.org',?,2,'test','now')""",
            (str(index), np.array([1, 0], dtype=np.float32).tobytes()),
        )
        conn.execute(
            """INSERT INTO video_index_ids(index_id,video_id,instance_domain,
            is_active,created_at,updated_at) VALUES(?,?,'example.org',1,1,1)""",
            (index + 1, str(index)),
        )
    conn.commit()
    rebuild_prepared_discovery(conn)
    rebuild_video_search_index(conn)


@pytest.mark.parametrize("index", range(6))
def test_direct_route_rejects_invalidity_before_live_fetch(
    engine_state, engine_client, monkeypatch, index
):
    """Invalid/high-error lookup is 404 before live fetch; live lookup overlays normally."""
    _seed(engine_state.db)
    fetched = []

    def detail(host, identity):
        """Replace only live PeerTube access and record its admitted identities."""
        fetched.append(identity)
        return {"title": "live title"}

    monkeypatch.setattr(video, "fetch_instance_video_dynamic", detail)
    response = engine_client.get(f"/api/video?id={index}&host=example.org")
    assert response.status_code == (200 if index == 0 else 404)
    assert fetched == ([str(index)] if index == 0 else [])
    if index == 0:
        assert response.json()["title"] == "live title"
    else:
        assert response.json() == {"error": "Video not found"}


@pytest.mark.parametrize(
    "path",
    [
        "/internal/discovery/fresh",
        "/internal/discovery/popular",
        "/internal/search/videos?q=availabilityword",
    ],
)
def test_paged_route_visibility_excludes_every_non_null_reason(engine_state, engine_client, path):
    """Shared route visibility keeps only the live low-error matrix row before cutting results."""
    _seed(engine_state.db)
    response = engine_client.get(path)
    assert response.status_code == 200
    assert [row["video_id"] for row in response.json()["rows"]] == ["0"]


@pytest.mark.parametrize("index", range(6))
def test_internal_resolve_and_metadata_keep_distinct_error_policies(
    engine_state, engine_client, index
):
    """Resolve admits high-error live seeds; metadata retains its existing output threshold."""
    _seed(engine_state.db)
    resolved = engine_client.post(
        "/internal/videos/resolve", json={"uuid": f"uuid-{index}", "host": "example.org"}
    )
    assert resolved.status_code == (200 if index in [0, 5] else 404)
    metadata = engine_client.post(
        "/internal/videos/metadata",
        json={"entries": [{"video_id": str(index), "instance_domain": "example.org"}]},
    )
    assert metadata.status_code == 200
    assert metadata.json()["count"] == int(index == 0)
