"""Engine global video-facet contract tests."""
from __future__ import annotations


def _install_schema(conn) -> None:
    """Create the minimal canonical schema needed by facet aggregation."""
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
            ("b","two.example","c2","uk","Ukrainian","education","13",'["linux", ""]',None,0),
            ("c","three.example","c3",None,None,"Music","4",'not-json',None,0),
            ("d","blocked.example","c4","en","English","Music","5",'["hidden"]',None,0),
        ],
    )
    conn.execute("INSERT INTO instance_denylist(host,is_active) VALUES ('blocked.example',1)")


def test_facets_count_visible_distinct_video_membership(engine_client, engine_state) -> None:
    """Facet counts match filterable visible videos, not duplicate JSON occurrences."""
    _install_schema(engine_state.db)
    response = engine_client.get("/internal/video-facets")
    assert response.status_code == 200
    payload = response.json()
    assert {row["value"]: row["count"] for row in payload["tags"]}["linux"] == 2
    assert payload["categories"][0] == {"value": "Education", "category_id": "13", "count": 2}
    languages = {row["value"]: row for row in payload["languages"]}
    assert languages["uk"]["count"] == 2
    assert languages["_unknown"]["count"] == 1
    assert payload["coverage"]["language"] == {"known": 2, "unknown": 1, "total": 3, "ratio": 2 / 3}
    assert "blocked.example" not in {row["value"] for row in payload["instances"]}


def test_facets_conflicting_category_ids_return_null_and_empty_corpus_is_safe(engine_client, engine_state) -> None:
    """Conflicting category identity is not invented and zero corpus has ratio zero."""
    _install_schema(engine_state.db)
    engine_state.db.execute("UPDATE videos SET category='Education', category_id='99' WHERE video_id='c'")
    response = engine_client.get("/internal/video-facets")
    education = next(row for row in response.json()["categories"] if row["value"].lower() == "education")
    assert education["category_id"] is None

    engine_state.db.execute("UPDATE videos SET invalid_reason='bad'")
    empty = engine_client.get("/internal/video-facets").json()
    assert empty["languages"] == []
    assert empty["coverage"]["language"] == {"known": 0, "unknown": 0, "total": 0, "ratio": 0.0}



def test_tag_facets_ignore_non_array_json_shapes(engine_client, engine_state) -> None:
    """Facet tag membership comes only from textual members of JSON arrays."""
    _install_schema(engine_state.db)
    engine_state.db.execute("DELETE FROM instance_denylist")
    engine_state.db.execute("DELETE FROM videos")
    rows = [
        ("array", "shape.example", "c1", "en", "English", "Other", "1", '["linux"]', None, 0),
        ("object", "shape.example", "c2", "en", "English", "Other", "1", '{"x":"linux"}', None, 0),
        ("string", "shape.example", "c3", "en", "English", "Other", "1", '"linux"', None, 0),
        ("number", "shape.example", "c4", "en", "English", "Other", "1", '123', None, 0),
        ("json-null", "shape.example", "c5", "en", "English", "Other", "1", 'null', None, 0),
        ("malformed", "shape.example", "c6", "en", "English", "Other", "1", '{bad', None, 0),
    ]
    engine_state.db.executemany(
        """
        INSERT INTO videos(video_id,instance_domain,channel_id,language,language_label,category,category_id,tags_json,invalid_reason,error_count)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )

    payload = engine_client.get("/internal/video-facets").json()
    assert {row["value"]: row["count"] for row in payload["tags"]} == {"linux": 1}


def test_facets_cap_top_values_and_use_deterministic_tie_order(engine_client, engine_state) -> None:
    """Positive/negative: top-N facets are capped and equal counts sort by normalized value."""
    _install_schema(engine_state.db)
    # Replace the small fixture with 105 one-video tags/instances of equal count.
    engine_state.db.execute("DELETE FROM instance_denylist")
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

    payload = engine_client.get("/internal/video-facets").json()
    assert len(payload["tags"]) == 100
    assert len(payload["instances"]) == 100
    assert [row["value"] for row in payload["tags"][:3]] == ["tag-000", "tag-001", "tag-002"]
    assert payload["tags"][-1]["value"] == "tag-099"
    assert "tag-104" not in {row["value"] for row in payload["tags"]}
