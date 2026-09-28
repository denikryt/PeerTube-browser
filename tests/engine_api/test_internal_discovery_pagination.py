"""Regression coverage for Discovery pagination invariants and Random traversal."""
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest

from engine.server.api.services import discovery_service
from engine.server.data.random_cache import open_random_provider_readonly
from engine.server.db.bootstrap import bootstrap_engine_random_cache_db
from engine.server.db.migrations.apply import apply_video_index_ids_migration


def _install_canonical_schema(conn: sqlite3.Connection) -> None:
    """Install the minimal canonical schema shared by paged provider tests."""
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE interaction_signals (
          video_uuid TEXT, instance_domain TEXT, likes_count INTEGER DEFAULT 0,
          undo_likes_count INTEGER DEFAULT 0, signal_score REAL DEFAULT 0,
          PRIMARY KEY(video_uuid, instance_domain)
        );
        CREATE TABLE instance_denylist (
          host TEXT PRIMARY KEY, is_active INTEGER, reason TEXT, note TEXT,
          created_at INTEGER, updated_at INTEGER
        );
        CREATE TABLE channel_moderation (
          channel_id TEXT, instance_domain TEXT, status TEXT, reason TEXT,
          source_video_url TEXT, updated_at INTEGER, created_at INTEGER,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT,
          channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT,
          account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT,
          category_id TEXT, language TEXT, language_label TEXT, published_at INTEGER,
          video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER,
          likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER,
          preview_path TEXT, popularity REAL, last_checked_at INTEGER,
          error_count INTEGER DEFAULT 0, invalid_reason TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT, instance_domain TEXT, embedding_dim INTEGER, model_name TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_tags (
          tag TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL,
          PRIMARY KEY(tag, video_id, instance_domain)
        ) WITHOUT ROWID;
        """
    )


def _insert_video(
    conn: sqlite3.Connection,
    video_id: str,
    *,
    instance: str = "example.org",
    channel_id: str | None = None,
    published_at: int | None = 100,
    popularity: float | None = 1.0,
    likes: int | None = 1,
    views: int | None = 1,
    language: str | None = "uk",
    category: str | None = "Education",
    category_id: str | None = "13",
    tags_json: str | None = '["linux"]',
    invalid_reason: str | None = None,
    with_embedding: bool = True,
) -> None:
    """Insert one browser-visible canonical video, optionally without an embedding."""
    channel = channel_id or f"c-{video_id}"
    conn.execute(
        "INSERT OR IGNORE INTO channels(channel_id, instance_domain, display_name, avatar_url) VALUES (?,?,?,NULL)",
        (channel, instance, f"Channel {video_id}"),
    )
    conn.execute(
        """
        INSERT INTO videos VALUES (
          ?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, 60,
          NULL, NULL, ?, ?, 0, 0, 0, NULL, ?, 1, 0, ?
        )
        """,
        (
            video_id,
            f"uuid-{video_id}",
            instance,
            channel,
            f"Channel {video_id}",
            f"Title {video_id}",
            tags_json,
            category,
            category_id,
            language,
            "Ukrainian" if language else None,
            published_at,
            views,
            likes,
            popularity,
            invalid_reason,
        ),
    )
    if with_embedding:
        conn.execute(
            "INSERT INTO video_embeddings(video_id,instance_domain,embedding_dim,model_name) VALUES (?,?,3,'test')",
            (video_id, instance),
        )
    # The fixture mirrors updater-prepared membership for the default JSON-array tags.
    try:
        parsed_tags = json.loads(tags_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed_tags = []
    if isinstance(parsed_tags, list):
        memberships = {str(tag).strip().lower() for tag in parsed_tags if isinstance(tag, str) and str(tag).strip()}
        conn.executemany(
            "INSERT OR IGNORE INTO video_tags(tag,video_id,instance_domain) VALUES (?,?,?)",
            [(tag, video_id, instance) for tag in sorted(memberships)],
        )


def _decode_cursor(token: str) -> dict[str, object]:
    """Decode one Engine cursor for assertions about its public opacity contract."""
    raw = token + "=" * (-len(token) % 4)
    return json.loads(base64.urlsafe_b64decode(raw).decode("utf-8"))


def _page_all(engine_client, source: str, *, limit: int, extra: str = "") -> list[str]:
    """Follow provider cursors until terminal and return stable video identities."""
    cursor: str | None = None
    rows: list[str] = []
    for _ in range(100):
        query = f"limit={limit}{extra}"
        if cursor:
            query += f"&cursor={cursor}"
        response = engine_client.get(f"/internal/discovery/{source}?{query}")
        assert response.status_code == 200, response.text
        body = response.json()
        rows.extend(str(item["video_id"]) for item in body["rows"])
        cursor = body["pagination"]["next_cursor"]
        if cursor is None:
            return rows
    raise AssertionError("provider cursor did not terminate")


def test_fresh_limit_50_and_null_groups_form_complete_total_order(engine_state, engine_client) -> None:
    """Positive: Fresh pages 50+ rows and traverses known->NULL groups without loss."""
    _install_canonical_schema(engine_state.db)
    for idx in range(51):
        _insert_video(engine_state.db, f"known-{idx:02d}", published_at=1000 - idx)
    for suffix in ("a", "b", "c"):
        _insert_video(engine_state.db, f"null-{suffix}", published_at=None)
    engine_state.db.commit()

    first = engine_client.get("/internal/discovery/fresh?limit=50")
    assert first.status_code == 200
    assert len(first.json()["rows"]) == 50
    assert first.json()["pagination"]["has_more"] is True
    cursor_payload = _decode_cursor(first.json()["pagination"]["next_cursor"])
    assert all(value is not None for value in cursor_payload["after"].values())

    paged = _page_all(engine_client, "fresh", limit=7)
    expected = [f"known-{idx:02d}" for idx in range(51)] + ["null-a", "null-b", "null-c"]
    assert paged == expected
    assert len(paged) == len(set(paged))


def test_fresh_cursor_rejects_filter_change_and_malformed_null_key(engine_state, engine_client) -> None:
    """Negative: ordered continuation cannot cross filter identity or carry NULL sort keys."""
    _install_canonical_schema(engine_state.db)
    for idx in range(3):
        _insert_video(engine_state.db, f"v{idx}", published_at=100 - idx)
    engine_state.db.commit()
    first = engine_client.get("/internal/discovery/fresh?limit=1&language=uk").json()
    cursor = first["pagination"]["next_cursor"]
    changed = engine_client.get(f"/internal/discovery/fresh?limit=1&language=en&cursor={cursor}")
    assert changed.status_code == 400
    wrong_source = engine_client.get(
        f"/internal/discovery/popular?limit=1&language=uk&cursor={cursor}"
    )
    assert wrong_source.status_code == 400

    payload = _decode_cursor(cursor)
    payload["after"]["published_sort"] = None
    bad = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    malformed = engine_client.get(f"/internal/discovery/fresh?limit=1&language=uk&cursor={bad}")
    assert malformed.status_code == 400

    payload = _decode_cursor(cursor)
    payload["after"]["published_is_null"] = "0"
    bad_type = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    malformed_type = engine_client.get(
        f"/internal/discovery/fresh?limit=1&language=uk&cursor={bad_type}"
    )
    assert malformed_type.status_code == 400

    payload = _decode_cursor(cursor)
    payload["v"] = True
    bad_version_type = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert (
        engine_client.get(
            f"/internal/discovery/fresh?limit=1&language=uk&cursor={bad_version_type}"
        ).status_code
        == 400
    )


def test_popular_uses_only_popularity_then_identity_and_pages_without_embeddings(engine_state, engine_client) -> None:
    """Positive: Trending ignores legacy tie-breakers and embedding eligibility across pages."""
    _install_canonical_schema(engine_state.db)
    for idx in range(51):
        _insert_video(
            engine_state.db,
            f"known-{idx:02d}",
            popularity=10,
            likes=idx,
            views=1000 - idx,
            published_at=idx,
            with_embedding=idx != 25,
        )
    _insert_video(engine_state.db, "top", popularity=11, likes=0, views=0, published_at=0, with_embedding=False)
    engine_state.db.commit()

    first = engine_client.get("/internal/discovery/popular?limit=50")
    assert first.status_code == 200
    assert len(first.json()["rows"]) == 50
    cursor_payload = _decode_cursor(first.json()["pagination"]["next_cursor"])
    assert set(cursor_payload["after"]) == {"popularity", "instance_domain", "video_id"}

    paged = _page_all(engine_client, "popular", limit=7)
    expected = ["top", *[f"known-{idx:02d}" for idx in range(51)]]
    assert paged == expected
    assert "known-25" in paged
    assert len(paged) == len(set(paged))



def test_popular_cursor_rejects_filter_change_and_cross_source_reuse(engine_state, engine_client) -> None:
    """Positive/negative: Popular continues only under the same source and filters."""
    _install_canonical_schema(engine_state.db)
    for idx in range(3):
        _insert_video(
            engine_state.db,
            f"v{idx}",
            popularity=100 - idx,
            likes=10 - idx,
            views=20 - idx,
            published_at=100 - idx,
            category="Education",
        )
    engine_state.db.commit()

    first = engine_client.get("/internal/discovery/popular?limit=1&category=Education")
    assert first.status_code == 200
    cursor = first.json()["pagination"]["next_cursor"]
    assert cursor

    continued = engine_client.get(
        f"/internal/discovery/popular?limit=1&category=Education&cursor={cursor}"
    )
    assert continued.status_code == 200
    assert continued.json()["rows"]

    changed_filter = engine_client.get(
        f"/internal/discovery/popular?limit=1&category=Music&cursor={cursor}"
    )
    assert changed_filter.status_code == 400

    wrong_source = engine_client.get(
        f"/internal/discovery/fresh?limit=1&category=Education&cursor={cursor}"
    )
    assert wrong_source.status_code == 400

def test_popular_signals_do_not_change_order_and_old_cursor_shape_is_rejected(engine_state, engine_client) -> None:
    """Negative: signal-only changes and legacy cursor keys cannot alter the new Trending contract."""
    _install_canonical_schema(engine_state.db)
    _insert_video(engine_state.db, "a", popularity=5, likes=1, views=1, published_at=1)
    _insert_video(engine_state.db, "b", popularity=4, likes=999, views=999, published_at=999)
    engine_state.db.execute(
        "INSERT INTO interaction_signals(video_uuid,instance_domain,likes_count,undo_likes_count,signal_score) VALUES ('uuid-b','example.org',1000,0,9999)"
    )
    engine_state.db.commit()

    first = engine_client.get("/internal/discovery/popular?limit=1")
    assert first.status_code == 200
    assert [row["video_id"] for row in first.json()["rows"]] == ["a"]
    cursor = first.json()["pagination"]["next_cursor"]
    second = engine_client.get(f"/internal/discovery/popular?limit=1&cursor={cursor}")
    assert second.status_code == 200
    assert [row["video_id"] for row in second.json()["rows"]] == ["b"]

    legacy = _decode_cursor(cursor)
    legacy["after"] = {
        "rank_score": 5.0,
        "effective_likes_is_null": 0,
        "effective_likes_sort": 1,
        "views_is_null": 0,
        "views_sort": 1,
        "published_is_null": 0,
        "published_sort": 1,
        "instance_domain": "example.org",
        "video_id": "a",
    }
    legacy_cursor = base64.urlsafe_b64encode(json.dumps(legacy).encode()).decode().rstrip("=")
    assert engine_client.get(f"/internal/discovery/popular?limit=1&cursor={legacy_cursor}").status_code == 400


def test_popular_cursor_rejects_non_finite_popularity(engine_state, engine_client) -> None:
    """Negative: Trending continuation rejects non-finite numeric popularity at decode boundary."""
    _install_canonical_schema(engine_state.db)
    _insert_video(engine_state.db, "a", popularity=5)
    _insert_video(engine_state.db, "b", popularity=4)
    engine_state.db.commit()
    cursor = engine_client.get("/internal/discovery/popular?limit=1").json()["pagination"]["next_cursor"]
    payload = _decode_cursor(cursor)
    payload["after"]["popularity"] = float("inf")
    bad = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert engine_client.get(f"/internal/discovery/popular?limit=1&cursor={bad}").status_code == 400


def test_fresh_without_embedding_is_eligible_but_invalid_video_is_not(engine_state, engine_client) -> None:
    """Positive/negative: Fresh eligibility is canonical visibility, not embedding presence."""
    _install_canonical_schema(engine_state.db)
    _insert_video(engine_state.db, "no-embedding", published_at=20, with_embedding=False)
    _insert_video(engine_state.db, "invalid", published_at=30, invalid_reason="deleted", with_embedding=False)
    engine_state.db.commit()

    response = engine_client.get("/internal/discovery/fresh?limit=10")
    assert response.status_code == 200
    ids = [row["video_id"] for row in response.json()["rows"]]
    assert "no-embedding" in ids
    assert "invalid" not in ids


def test_ordered_providers_filter_and_moderate_before_page_cut(engine_state, engine_client) -> None:
    """Positive/negative: invisible/nonmatching leaders never consume the requested page quota."""
    _install_canonical_schema(engine_state.db)
    for idx in range(8):
        category = "Music" if idx < 4 else "Education"
        instance = "blocked.example" if idx == 4 else "example.org"
        _insert_video(
            engine_state.db,
            f"v{idx}",
            published_at=1000 - idx,
            popularity=1000 - idx,
            category=category,
            instance=instance,
        )
    engine_state.db.execute("INSERT INTO instance_denylist(host,is_active) VALUES ('blocked.example',1)")
    engine_state.db.commit()

    for source in ("fresh", "popular"):
        response = engine_client.get(f"/internal/discovery/{source}?limit=2&category=Education")
        assert response.status_code == 200
        assert [row["video_id"] for row in response.json()["rows"]] == ["v5", "v6"]
        assert response.json()["pagination"]["has_more"] is True


def _create_random_files(tmp_path: Path, count: int) -> tuple[Path, Path]:
    """Create canonical and persisted-order files with deterministic 1..N identities."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    canonical = tmp_path / "canonical.db"
    artifact = tmp_path / "random.db"
    canonical_db = sqlite3.connect(canonical)
    canonical_db.row_factory = sqlite3.Row
    _install_canonical_schema(canonical_db)
    apply_video_index_ids_migration(canonical_db)
    for idx in range(1, count + 1):
        _insert_video(canonical_db, f"v{idx}", published_at=idx, popularity=float(idx))
        canonical_db.execute(
            "INSERT INTO video_index_ids(index_id,video_id,instance_domain,is_active,created_at,updated_at) VALUES (?,?, 'example.org',1,1,1)",
            (idx, f"v{idx}"),
        )
    canonical_db.commit()
    canonical_db.close()

    cache = sqlite3.connect(artifact)
    cache.row_factory = sqlite3.Row
    bootstrap_engine_random_cache_db(cache)
    cache.executemany(
        "INSERT INTO random_index_ids(position,index_id) VALUES (?,?)",
        [(idx, idx) for idx in range(1, count + 1)],
    )
    cache.execute(
        "INSERT INTO random_cache_meta(singleton_id,schema_version,build_id,built_at) VALUES (1,2,?,?)",
        ("a" * 32, "test"),
    )
    cache.commit()
    cache.close()
    return canonical, artifact


def _attach_random(engine_state, canonical: Path, artifact: Path) -> None:
    """Install a real read-only Random provider connection into the Engine state."""
    if engine_state.random_cache_db is not None:
        engine_state.random_cache_db.close()
    engine_state.random_cache_db = open_random_provider_readonly(artifact, canonical)


def test_random_limit_50_lookahead_wrap_and_cycle_are_lossless(tmp_path, monkeypatch, engine_state, engine_client) -> None:
    """Positive: Random uses one persisted circular order and never drops its lookahead row."""
    canonical, artifact = _create_random_files(tmp_path, 51)
    _attach_random(engine_state, canonical, artifact)
    monkeypatch.setattr(discovery_service.random, "randint", lambda _a, _b: 50)

    first = engine_client.get("/internal/discovery/random?limit=50")
    assert first.status_code == 200
    assert len(first.json()["rows"]) == 50
    assert first.json()["pagination"]["has_more"] is True

    # limit=1 makes every page boundary exercise the lookahead position.
    paged = _page_all(engine_client, "random", limit=1)
    assert paged == ["v50", "v51", *[f"v{i}" for i in range(1, 50)]]
    assert len(paged) == 51 == len(set(paged))




def test_random_single_row_is_terminal_even_when_limit_is_larger(tmp_path, monkeypatch, engine_state, engine_client) -> None:
    """Positive/negative boundary: one persisted row is returned once and cannot create continuation."""
    canonical, artifact = _create_random_files(tmp_path, 1)
    _attach_random(engine_state, canonical, artifact)
    monkeypatch.setattr(discovery_service.random, "randint", lambda _a, _b: 1)

    response = engine_client.get("/internal/discovery/random?limit=50")
    assert response.status_code == 200
    body = response.json()
    assert [row["video_id"] for row in body["rows"]] == ["v1"]
    assert body["pagination"] == {"limit": 50, "next_cursor": None, "has_more": False}


def test_random_sparse_filter_uses_at_most_two_joined_ranges(tmp_path, monkeypatch, engine_state, engine_client) -> None:
    """Positive/negative: sparse matches still fill via <=2 SQL ranges, with no Python chunk loop."""
    canonical, artifact = _create_random_files(tmp_path, 60)
    writer = sqlite3.connect(canonical)
    writer.execute("UPDATE videos SET tags_json='[]'")
    writer.execute("UPDATE videos SET tags_json='[\"rare\"]' WHERE video_id IN ('v2','v55')")
    writer.execute("DELETE FROM video_tags")
    writer.executemany(
        "INSERT INTO video_tags(tag,video_id,instance_domain) VALUES ('rare',?,'example.org')",
        [("v2",), ("v55",)],
    )
    writer.commit()
    writer.close()
    _attach_random(engine_state, canonical, artifact)
    monkeypatch.setattr(discovery_service.random, "randint", lambda _a, _b: 50)
    statements: list[str] = []
    engine_state.random_cache_db.set_trace_callback(statements.append)

    response = engine_client.get("/internal/discovery/random?limit=1&tag=rare")
    assert response.status_code == 200
    assert [row["video_id"] for row in response.json()["rows"]] == ["v55"]
    selects = [sql for sql in statements if "FROM main.random_index_ids" in sql]
    assert 1 <= len(selects) <= 2
    assert response.json()["pagination"]["has_more"] is True


def test_random_reads_current_metadata_and_moderation_not_artifact_snapshot(tmp_path, monkeypatch, engine_state, engine_client) -> None:
    """Positive/negative: current canonical changes control filtering after artifact creation."""
    canonical, artifact = _create_random_files(tmp_path, 3)
    writer = sqlite3.connect(canonical)
    writer.execute("UPDATE videos SET category='Music' WHERE video_id='v1'")
    writer.execute("INSERT INTO instance_denylist(host,is_active) VALUES ('example.org',0)")
    writer.commit()
    writer.close()
    _attach_random(engine_state, canonical, artifact)
    monkeypatch.setattr(discovery_service.random, "randint", lambda _a, _b: 1)

    before = engine_client.get("/internal/discovery/random?limit=2&category=Education")
    assert [row["video_id"] for row in before.json()["rows"]] == ["v2", "v3"]

    writer = sqlite3.connect(canonical)
    writer.execute("UPDATE instance_denylist SET is_active=1 WHERE host='example.org'")
    writer.commit()
    writer.close()
    after = engine_client.get("/internal/discovery/random?limit=2&category=Education")
    assert after.status_code == 200
    assert after.json()["rows"] == []
    assert after.json()["pagination"]["has_more"] is False


def test_random_cursor_derives_wrap_from_positions_and_rejects_malformed_positions(
    tmp_path, monkeypatch, engine_state, engine_client
) -> None:
    """Positive/negative: cursor stores only traversal positions; malformed positions still fail."""
    canonical, artifact = _create_random_files(tmp_path, 4)
    _attach_random(engine_state, canonical, artifact)
    monkeypatch.setattr(discovery_service.random, "randint", lambda _a, _b: 4)

    first = engine_client.get("/internal/discovery/random?limit=1").json()
    first_payload = _decode_cursor(first["pagination"]["next_cursor"])
    assert "wrapped" not in first_payload
    assert first_payload["resume_position"] < first_payload["start_position"]

    continued = engine_client.get(
        f"/internal/discovery/random?limit=1&cursor={first['pagination']['next_cursor']}"
    )
    assert continued.status_code == 200
    assert [row["video_id"] for row in continued.json()["rows"]] == ["v1"]

    malformed_payload = _decode_cursor(first["pagination"]["next_cursor"])
    malformed_payload["resume_position"] = True
    malformed = base64.urlsafe_b64encode(json.dumps(malformed_payload).encode()).decode().rstrip("=")
    assert engine_client.get(
        f"/internal/discovery/random?limit=1&cursor={malformed}"
    ).status_code == 400


def test_random_empty_unavailable_and_filter_bound_cursor_are_distinct(tmp_path, monkeypatch, engine_state, engine_client) -> None:
    """Negative boundaries: valid empty is 200, missing provider is 503, changed filters reject cursor."""
    canonical, artifact = _create_random_files(tmp_path, 0)
    _attach_random(engine_state, canonical, artifact)
    empty = engine_client.get("/internal/discovery/random?limit=20")
    assert empty.status_code == 200
    assert empty.json()["rows"] == []
    assert empty.json()["pagination"]["next_cursor"] is None

    engine_state.random_cache_db.close()
    engine_state.random_cache_db = None
    unavailable = engine_client.get("/internal/discovery/random?limit=20")
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "random_provider_unavailable"

    canonical2, artifact2 = _create_random_files(tmp_path / "nonempty", 3)
    _attach_random(engine_state, canonical2, artifact2)
    monkeypatch.setattr(discovery_service.random, "randint", lambda _a, _b: 1)
    first = engine_client.get("/internal/discovery/random?limit=1&language=uk").json()
    changed = engine_client.get(
        f"/internal/discovery/random?limit=1&language=en&cursor={first['pagination']['next_cursor']}"
    )
    assert changed.status_code == 400

    stale_payload = _decode_cursor(first["pagination"]["next_cursor"] )
    stale_payload["build_id"] = "b" * 32
    stale_cursor = base64.urlsafe_b64encode(json.dumps(stale_payload).encode()).decode().rstrip("=")
    stale = engine_client.get(
        f"/internal/discovery/random?limit=1&language=uk&cursor={stale_cursor}"
    )
    assert stale.status_code == 400
    assert stale.json()["code"] == "stale_cursor"
