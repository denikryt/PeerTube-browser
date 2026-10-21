"""Engine prepared video-facet contract tests."""
from __future__ import annotations

from engine.server.data.prepared_discovery import rebuild_prepared_discovery


def _install_schema(conn) -> None:
    """Create the canonical source schema consumed by prepared facet rebuild."""
    conn.executescript(
        """
        CREATE TABLE videos (
          video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, channel_id TEXT,
          language TEXT, language_label TEXT, category TEXT, category_id TEXT,
          tags_json TEXT, invalid_reason TEXT, error_count INTEGER,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE instance_denylist (host TEXT PRIMARY KEY, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE channel_moderation (channel_id TEXT, instance_domain TEXT, status TEXT, PRIMARY KEY(channel_id, instance_domain));
        """
    )
    conn.executemany(
        """
        INSERT INTO videos(video_id,instance_domain,channel_id,language,language_label,category,category_id,tags_json,invalid_reason,error_count)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        [
            ("a","one.example","c1","uk","Ukrainian","Education","13",'["Linux","linux","LINUX"]',None,0),
            ("b","two.example","c2","uk","Ukrainian","education","13",'["linux", ""]',None,999),
            ("c","three.example","c3",None,None,"Music","4",'not-json',None,0),
            ("d","blocked.example","c4","en","English","Music","5",'["hidden"]',None,0),
        ],
    )
    conn.execute("INSERT INTO instance_denylist(host,is_active) VALUES ('blocked.example',1)")
    conn.commit()


def test_facets_read_prepared_canonical_metadata_snapshot(engine_client, engine_state) -> None:
    """Positive: route returns prepared metadata statistics including runtime-policy-hidden rows."""
    _install_schema(engine_state.db)
    rebuild_prepared_discovery(engine_state.db)

    response = engine_client.get("/internal/video-facets")

    assert response.status_code == 200
    payload = response.json()
    assert {row["value"]: row["count"] for row in payload["tags"]}["linux"] == 2
    assert payload["categories"][0] == {"value": "Education", "category_id": "13", "count": 2}
    languages = {row["value"]: row for row in payload["languages"]}
    assert languages["uk"]["count"] == 2
    assert languages["_unknown"]["count"] == 1
    assert payload["coverage"]["language"] == {"known": 3, "unknown": 1, "total": 4, "ratio": 0.75}
    assert "blocked.example" in {row["value"] for row in payload["instances"]}


def test_facets_missing_or_corrupt_snapshot_returns_controlled_503(engine_client, engine_state) -> None:
    """Negative: runtime never falls back to corpus aggregation when prepared facets are unavailable."""
    _install_schema(engine_state.db)
    missing = engine_client.get("/internal/video-facets")
    assert missing.status_code == 503
    assert missing.json()["code"] == "video_facets_unavailable"

    rebuild_prepared_discovery(engine_state.db)
    engine_state.db.execute("UPDATE video_facets_snapshot SET payload_json='{}'")
    engine_state.db.commit()
    corrupt = engine_client.get("/internal/video-facets")
    assert corrupt.status_code == 503
    assert corrupt.json()["code"] == "video_facets_unavailable"


def test_facets_conflicting_category_ids_and_empty_corpus_are_prepared_safely(engine_client, engine_state) -> None:
    """Positive/negative: ambiguous category identity becomes null and zero corpus remains valid."""
    _install_schema(engine_state.db)
    engine_state.db.execute("UPDATE videos SET category='Education', category_id='99' WHERE video_id='c'")
    engine_state.db.commit()
    rebuild_prepared_discovery(engine_state.db)
    education = next(
        row for row in engine_client.get("/internal/video-facets").json()["categories"]
        if row["value"].lower() == "education"
    )
    assert education["category_id"] is None

    engine_state.db.execute("UPDATE videos SET invalid_reason='bad'")
    engine_state.db.commit()
    rebuild_prepared_discovery(engine_state.db)
    empty = engine_client.get("/internal/video-facets").json()
    assert empty["languages"] == []
    assert empty["coverage"]["language"] == {
        "known": 0,
        "unknown": 0,
        "total": 0,
        "ratio": 0.0,
    }


def test_facets_cap_prepared_top_values_with_deterministic_tie_order(engine_client, engine_state) -> None:
    """Positive/negative: top-N prepared values are capped and ties sort by normalized value."""
    _install_schema(engine_state.db)
    engine_state.db.execute("DELETE FROM videos")
    rows = []
    for idx in range(105):
        value = f"tag-{idx:03d}"
        rows.append((f"v{idx}", f"host-{idx:03d}.example", f"c{idx}", "uk", "Ukrainian", "Education", "13", f'["{value}"]', None, 0))
    engine_state.db.executemany(
        """
        INSERT INTO videos(video_id,instance_domain,channel_id,language,language_label,category,category_id,tags_json,invalid_reason,error_count)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    engine_state.db.commit()
    rebuild_prepared_discovery(engine_state.db)

    payload = engine_client.get("/internal/video-facets").json()
    assert len(payload["tags"]) == 100
    assert len(payload["instances"]) == 100
    assert [row["value"] for row in payload["tags"][:3]] == ["tag-000", "tag-001", "tag-002"]
    assert payload["tags"][-1]["value"] == "tag-099"
    assert "tag-104" not in {row["value"] for row in payload["tags"]}
