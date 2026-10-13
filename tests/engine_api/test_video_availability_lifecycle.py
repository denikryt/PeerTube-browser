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


@pytest.mark.parametrize("negative", ["not_found", "gone"])
def test_publisher_drives_routes_facets_tags_and_search(
    engine_state, engine_client, tmp_path, monkeypatch, negative
):
    """Actual publication preserves membership/IDs while consumers hide and recover."""
    import sqlite3

    from engine.server.data.prepared_discovery import (
        fetch_prepared_video_facets,
        prepared_discovery_available,
    )
    from engine.server.db.jobs.updater import staging
    from engine.server.db.jobs.updater.availability_publish import (
        publish_existing_video_availability,
    )

    prod, stage = tmp_path / "prod.db", tmp_path / "stage.db"
    engine_state.db.close()
    engine_state.db = sqlite3.connect(prod, check_same_thread=False)
    engine_state.db.row_factory = sqlite3.Row
    conn = engine_state.db
    _seed(conn)
    # Keep one row with a unique public tag; other rows remain excluded by their
    # canonical or independent error policy. This also proves tag zero-count behavior.
    conn.execute("UPDATE videos SET tags_json='[\"recovered-tag\"]' WHERE video_id='0'")
    conn.commit()
    rebuild_prepared_discovery(conn)
    staging.init_staging_db(stage, ROOT / "engine/crawler/schema.sql")
    with sqlite3.connect(stage) as evidence:
        evidence.execute(
            "INSERT INTO video_availability_work VALUES('0','example.org','uuid-0',NULL,NULL,NULL)"
        )
    monkeypatch.setattr(video, "fetch_instance_json", lambda *a: None)
    membership = [tuple(r) for r in conn.execute("SELECT * FROM video_tags ORDER BY tag,video_id")]
    stable = [tuple(r) for r in conn.execute("SELECT * FROM video_index_ids")]
    from engine.server.data.random_cache import open_random_provider_readonly
    from engine.server.db.bootstrap import bootstrap_engine_random_cache_db

    cache_path = tmp_path / "random.db"
    with sqlite3.connect(cache_path) as cache:
        bootstrap_engine_random_cache_db(cache)
        cache.executemany("INSERT INTO random_index_ids VALUES(?,?)", [(i, i) for i in range(1, 7)])
        cache.execute("INSERT INTO random_cache_meta VALUES(1,2,?,'test')", ("a" * 32,))
    engine_state.random_cache_db = open_random_provider_readonly(cache_path, prod)
    for outcome, checked, visible in [(negative, 3000, False), ("available", 5000, True)]:
        with sqlite3.connect(stage) as evidence:
            evidence.execute(
                "UPDATE video_availability_work SET outcome=?,checked_at=?", (outcome, checked)
            )
        publish_existing_video_availability(
            prod, stage, sweep_report=staging.video_availability_report(stage, missing_uuid=0)
        )
        assert not prepared_discovery_available(conn)
        assert [
            tuple(r) for r in conn.execute("SELECT * FROM video_tags ORDER BY tag,video_id")
        ] == membership
        rebuild_prepared_discovery(conn)
        rebuild_video_search_index(conn)
        assert [
            tuple(r) for r in conn.execute("SELECT * FROM video_tags ORDER BY tag,video_id")
        ] == membership
        assert [tuple(r) for r in conn.execute("SELECT * FROM video_index_ids")] == stable
        counts = {r["value"]: r["count"] for r in fetch_prepared_video_facets(conn)["tags"]}
        assert counts.get("recovered-tag", 0) == int(visible)
        docs = conn.execute("SELECT COUNT(*) FROM video_search_docs WHERE video_id='0'").fetchone()[
            0
        ]
        assert docs == int(visible)
        detail = engine_client.get("/api/video?id=0&host=example.org")
        assert detail.status_code == (200 if visible else 404)
        if not visible:
            assert detail.json() == {"error": "Video not found"}
        resolved = engine_client.post(
            "/internal/videos/resolve", json={"uuid": "uuid-0", "host": "example.org"}
        )
        assert resolved.status_code == (200 if visible else 404)
        metadata = engine_client.post(
            "/internal/videos/metadata",
            json={"entries": [{"video_id": "0", "instance_domain": "example.org"}]},
        )
        assert metadata.status_code == 200 and metadata.json()["count"] == int(visible)
        for path in (
            "/internal/discovery/fresh?tag=recovered-tag",
            "/internal/discovery/popular?tag=recovered-tag",
            "/internal/discovery/random?tag=recovered-tag",
            "/internal/search/videos?q=availabilityword&tag=recovered-tag",
        ):
            response = engine_client.get(path)
            assert response.status_code == 200, (path, response.text)
            assert [r["video_id"] for r in response.json()["rows"]] == (["0"] if visible else [])
        from data.metadata import fetch_metadata_by_index_ids
        from data.similarity_candidates import SimilarityCandidatesPolicy, get_similar_candidates

        assert list(fetch_metadata_by_index_ids(conn, [1], error_threshold=3)) == (
            [1] if visible else []
        )
        # Replace only the heavyweight ANN edge. The real candidate service resolves
        # current canonical metadata and enforces its existing seed/author caps.
        engine_state.compute_similar_items = lambda *a: [
            {"video_id": "0", "instance_domain": "example.org", "score": 0.9}
        ]
        candidates = get_similar_candidates(
            engine_state,
            {
                "video_id": "seed",
                "instance_domain": "other.org",
                "channel_id": "source",
                "embedding": np.array([1, 0], dtype=np.float32),
            },
            1,
            SimilarityCandidatesPolicy(use_cache=False, allow_cache_write=False),
        )
        assert [r["video_id"] for r in candidates] == (["0"] if visible else [])
    engine_state.random_cache_db.close()
    engine_state.random_cache_db = None


@pytest.mark.parametrize("remote_success", [False, True])
def test_real_metadata_refresh_cannot_block_independent_publication(
    engine_state, engine_client, tmp_path, monkeypatch, remote_success
):
    """Remote failure still advances metadata clock; neither kind versions availability."""
    import sqlite3

    from engine.server.data.prepared_discovery import prepared_discovery_available
    from engine.server.db.jobs.updater import staging
    from engine.server.db.jobs.updater.availability_publish import (
        publish_existing_video_availability,
    )

    prod, stage = tmp_path / "prod.db", tmp_path / "stage.db"
    engine_state.db.close()
    engine_state.db = sqlite3.connect(prod, check_same_thread=False)
    engine_state.db.row_factory = sqlite3.Row
    conn = engine_state.db
    _seed(conn)
    # A and B are independent available identities before the sweep.
    conn.execute(
        "UPDATE videos SET invalid_reason=NULL,invalid_at=NULL,error_count=0 "
        "WHERE video_id IN ('0','1')"
    )
    conn.commit()
    rebuild_prepared_discovery(conn)
    staging.init_staging_db(stage, ROOT / "engine/crawler/schema.sql")
    with sqlite3.connect(stage) as evidence:
        evidence.executemany(
            "INSERT INTO video_availability_work VALUES(?,?,?,?,?,NULL)",
            [
                ("0", "example.org", "uuid-0", "not_found", 3000),
                ("1", "example.org", "uuid-1", "gone", 3000),
            ],
        )
    monkeypatch.setattr(
        video,
        "fetch_instance_json",
        lambda *a: {"uuid": "uuid-0", "name": "remote"} if remote_success else None,
    )
    monkeypatch.setattr(video, "now_ms", lambda: 5000)
    response = engine_client.get("/api/video?id=0&host=example.org")
    assert response.status_code == 200
    assert response.json()["title"] == ("remote" if remote_success else "availabilityword")
    assert tuple(
        conn.execute(
            "SELECT last_checked_at,invalid_reason,invalid_at FROM videos WHERE video_id='0'"
        ).fetchone()
    ) == (5000, None, None)
    result = publish_existing_video_availability(
        prod, stage, sweep_report=staging.video_availability_report(stage, missing_uuid=0)
    )
    assert result.applied_absent == 2 and not prepared_discovery_available(conn)
    assert [
        tuple(r)
        for r in conn.execute(
            "SELECT video_id,last_checked_at,invalid_reason,invalid_at FROM videos "
            "WHERE video_id IN ('0','1') ORDER BY video_id"
        )
    ] == [("0", 5000, "not_found", 3000), ("1", 1, "gone", 3000)]
