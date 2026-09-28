"""Random artifact ownership, validation, and read-only runtime regression tests."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data import random_cache  # noqa: E402
from data.random_cache import (  # noqa: E402
    RandomCacheUnavailable,
    open_random_cache_artifact_readonly,
    open_random_provider_readonly,
    read_random_cache_meta,
    rebuild_random_cache,
)
from engine.server.db.bootstrap import bootstrap_engine_random_cache_db  # noqa: E402
from engine.server.db.migrations.apply import apply_video_index_ids_migration  # noqa: E402


def _canonical(path: Path, count: int = 3) -> None:
    """Create a minimal canonical DB accepted by the Random runtime attachment."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT,
          channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT,
          title TEXT, description TEXT, tags_json TEXT, category TEXT, category_id TEXT,
          language TEXT, language_label TEXT, published_at INTEGER, video_url TEXT, duration INTEGER,
          thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER,
          comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL, last_checked_at INTEGER,
          error_count INTEGER DEFAULT 0, invalid_reason TEXT, PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT, instance_domain TEXT, embedding_dim INTEGER, model_name TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_tags (
          tag TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL,
          PRIMARY KEY(tag, video_id, instance_domain)
        ) WITHOUT ROWID;
        CREATE TABLE instance_denylist (host TEXT PRIMARY KEY, is_active INTEGER, reason TEXT, note TEXT, created_at INTEGER, updated_at INTEGER);
        CREATE TABLE channel_moderation (channel_id TEXT, instance_domain TEXT, status TEXT, reason TEXT, source_video_url TEXT, updated_at INTEGER, created_at INTEGER, PRIMARY KEY(channel_id, instance_domain));
        """
    )
    apply_video_index_ids_migration(conn)
    for idx in range(1, count + 1):
        vid = f"v{idx}"
        conn.execute("INSERT OR IGNORE INTO channels VALUES (?, 'example.org', ?, NULL)", (f"c{idx}", f"Channel {idx}"))
        conn.execute(
            """
            INSERT INTO videos VALUES (?, ?, ?, 'example.org', ?, ?, NULL, NULL, NULL, ?, NULL, '[]',
            'Education', '13', 'uk', 'Ukrainian', ?, NULL, 60, NULL, NULL, ?, ?, 0, 0, 0, NULL, 1, 1, 0, NULL)
            """,
            (vid, f"uuid-{idx}", idx, f"c{idx}", f"c{idx}", f"Title {idx}", idx * 100, idx, idx),
        )
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'example.org', 3, 'test')", (vid,))
        conn.execute("INSERT INTO video_tags VALUES ('linux', ?, 'example.org')", (vid,))
        conn.execute(
            "INSERT INTO video_index_ids(index_id, video_id, instance_domain, is_active, created_at, updated_at) VALUES (?, ?, 'example.org', 1, 1, 1)",
            (idx, vid),
        )
    conn.commit()
    conn.close()


def _source_connection(path: Path) -> sqlite3.Connection:
    """Open the canonical fixture with the row factory required by the builder."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_readonly_artifact_missing_path_stays_missing(tmp_path: Path) -> None:
    """Negative path: runtime open never creates or bootstraps a missing artifact."""
    path = tmp_path / "missing.db"
    with pytest.raises(RandomCacheUnavailable):
        open_random_cache_artifact_readonly(path)
    assert not path.exists()


def test_provider_primary_and_attachment_are_read_only(tmp_path: Path) -> None:
    """Positive/negative path: valid provider reads both DBs but writes to neither."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    rebuild_random_cache(src, artifact, size=3, refresh=True)
    src.close()

    artifact_before = artifact.read_bytes()
    canonical_before = canonical.read_bytes()
    conn = open_random_provider_readonly(artifact, canonical)
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        assert read_random_cache_meta(conn)["count"] == 3
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM main.random_index_ids")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM canonical.videos")
    finally:
        conn.close()

    # Negative write attempts above must not mutate either authoritative file.
    assert artifact.read_bytes() == artifact_before
    assert canonical.read_bytes() == canonical_before


def test_rebuild_gets_fresh_uuid_and_skip_preserves_generation(tmp_path: Path) -> None:
    """Generation identity changes per rebuild but not for a valid sufficient skip."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    first = rebuild_random_cache(src, artifact, size=2, refresh=True, built_at=123)
    second = rebuild_random_cache(src, artifact, size=2, refresh=True, built_at=123)
    skipped = rebuild_random_cache(src, artifact, size=2, refresh=False, built_at=123)
    src.close()

    assert len(str(first["build_id"])) == 32
    assert str(first["build_id"]) != str(second["build_id"])
    assert skipped["rebuilt"] is False
    assert skipped["build_id"] == second["build_id"]




def test_no_refresh_rebuilds_undersized_or_incompatible_final_then_skips_sufficient(tmp_path: Path) -> None:
    """Positive/negative: no-refresh reuses only a valid final that already satisfies requested size."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical, count=4)
    src = _source_connection(canonical)
    try:
        small = rebuild_random_cache(src, artifact, size=1, refresh=True)
        grown = rebuild_random_cache(src, artifact, size=3, refresh=False)
        assert grown["rebuilt"] is True
        assert grown["count"] == 3
        assert grown["build_id"] != small["build_id"]

        writer = sqlite3.connect(artifact)
        writer.execute("CREATE TABLE unexpected_state(value TEXT)")
        writer.commit()
        writer.close()
        repaired = rebuild_random_cache(src, artifact, size=3, refresh=False)
        assert repaired["rebuilt"] is True
        assert repaired["build_id"] != grown["build_id"]

        skipped = rebuild_random_cache(src, artifact, size=3, refresh=False)
        assert skipped["rebuilt"] is False
        assert skipped["build_id"] == repaired["build_id"]
    finally:
        src.close()

    conn = sqlite3.connect(artifact)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == {"random_cache_meta", "random_index_ids"}
    finally:
        conn.close()


def test_failed_validation_does_not_replace_authoritative_generation(tmp_path: Path, monkeypatch) -> None:
    """Negative path: copy-on-publish keeps the old final artifact when validation fails."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    first = rebuild_random_cache(src, artifact, size=2, refresh=True)
    before = artifact.read_bytes()

    original = random_cache.open_random_cache_artifact_readonly
    def fail_temp(path: Path):
        if path != artifact:
            raise RandomCacheUnavailable("injected validation failure")
        return original(path)
    monkeypatch.setattr(random_cache, "open_random_cache_artifact_readonly", fail_temp)
    with pytest.raises(RandomCacheUnavailable):
        rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    assert artifact.read_bytes() == before
    conn = original(artifact)
    try:
        assert read_random_cache_meta(conn)["build_id"] == first["build_id"]
    finally:
        conn.close()
    assert not list(tmp_path.glob(".random.db.tmp-*"))


def test_zero_candidate_build_is_valid_empty_but_missing_metadata_is_invalid(tmp_path: Path) -> None:
    """Empty content is a completed generation; schema without completion metadata is unavailable."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical, count=0)
    src = _source_connection(canonical)
    built = rebuild_random_cache(src, artifact, size=20, refresh=True)
    src.close()
    assert built["count"] == 0
    conn = open_random_cache_artifact_readonly(artifact)
    conn.close()

    invalid = tmp_path / "invalid.db"
    bad = sqlite3.connect(invalid)
    bootstrap_engine_random_cache_db(bad)
    bad.close()
    with pytest.raises(RandomCacheUnavailable):
        open_random_cache_artifact_readonly(invalid)



def test_artifact_schema_contains_only_generation_metadata_and_stable_order(tmp_path: Path) -> None:
    """Positive/negative: derived Random DB never duplicates mutable video filter metadata."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    rebuild_random_cache(src, artifact, size=3, refresh=True)
    src.close()

    conn = sqlite3.connect(artifact)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == {"random_cache_meta", "random_index_ids"}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(random_index_ids)")}
        assert columns == {"position", "index_id"}
        assert not {"language", "category", "tags_json", "instance_domain", "channel_id"} & columns
    finally:
        conn.close()


def test_publication_failure_with_no_prior_final_leaves_provider_unavailable(tmp_path: Path, monkeypatch) -> None:
    """Negative: a failed atomic publish cannot expose a partial first generation."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)

    def fail_replace(_src, _dst):
        raise OSError("injected publication failure")

    monkeypatch.setattr(random_cache.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    assert not artifact.exists()
    assert not list(tmp_path.glob(".random.db.tmp-*"))
    with pytest.raises(RandomCacheUnavailable):
        open_random_cache_artifact_readonly(artifact)


def test_invalid_generation_identity_and_noncontiguous_order_are_rejected(tmp_path: Path) -> None:
    """Negative: malformed completion identity/order never becomes a valid runtime artifact."""
    invalid_id = tmp_path / "invalid-id.db"
    conn = sqlite3.connect(invalid_id)
    conn.row_factory = sqlite3.Row
    bootstrap_engine_random_cache_db(conn)
    conn.execute(
        "INSERT INTO random_cache_meta(singleton_id,schema_version,build_id,built_at) VALUES (1,2,'NOT-A-UUID','x')"
    )
    conn.commit()
    conn.close()
    with pytest.raises(RandomCacheUnavailable):
        open_random_cache_artifact_readonly(invalid_id)

    gap = tmp_path / "gap.db"
    conn = sqlite3.connect(gap)
    conn.row_factory = sqlite3.Row
    bootstrap_engine_random_cache_db(conn)
    conn.execute(
        "INSERT INTO random_cache_meta(singleton_id,schema_version,build_id,built_at) VALUES (1,2,?,'x')",
        ("a" * 32,),
    )
    conn.execute("INSERT INTO random_index_ids(position,index_id) VALUES (2,10)")
    conn.commit()
    conn.close()
    with pytest.raises(RandomCacheUnavailable):
        open_random_cache_artifact_readonly(gap)


def test_orphan_sibling_temp_is_ignored_when_authoritative_final_is_valid(tmp_path: Path) -> None:
    """Positive/negative: runtime consumes only final path and ignores interrupted temp names."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    built = rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()
    (tmp_path / ".random.db.tmp-orphan").write_bytes(b"partial")

    conn = open_random_cache_artifact_readonly(artifact)
    try:
        assert read_random_cache_meta(conn)["build_id"] == built["build_id"]
    finally:
        conn.close()

def test_provider_rejects_incomplete_canonical_attachment_without_writing(tmp_path: Path) -> None:
    """Positive/negative: complete canonical schema attaches; a missing required table is unavailable."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    provider = open_random_provider_readonly(artifact, canonical)
    provider.close()
    artifact_before = artifact.read_bytes()

    writer = sqlite3.connect(canonical)
    writer.execute("DROP TABLE video_tags")
    writer.commit()
    writer.close()
    with pytest.raises(RandomCacheUnavailable, match="missing required Random tables"):
        open_random_provider_readonly(artifact, canonical)
    assert artifact.read_bytes() == artifact_before

def test_build_failure_with_existing_final_preserves_authoritative_generation(tmp_path: Path, monkeypatch) -> None:
    """Negative: a failed temp population cannot mutate an existing final artifact."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    first = rebuild_random_cache(src, artifact, size=2, refresh=True)
    before = artifact.read_bytes()

    def fail_population(*_args, **_kwargs):
        raise RuntimeError("injected build failure")

    monkeypatch.setattr(random_cache, "populate_random_cache", fail_population)
    with pytest.raises(RuntimeError, match="build failure"):
        rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    assert artifact.read_bytes() == before
    conn = open_random_cache_artifact_readonly(artifact)
    try:
        assert read_random_cache_meta(conn)["build_id"] == first["build_id"]
    finally:
        conn.close()
    assert not list(tmp_path.glob(".random.db.tmp-*"))


def test_publication_failure_with_existing_final_preserves_authoritative_generation(tmp_path: Path, monkeypatch) -> None:
    """Negative: failed atomic replacement leaves the previous final byte-for-byte intact."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    first = rebuild_random_cache(src, artifact, size=2, refresh=True)
    before = artifact.read_bytes()

    def fail_replace(_src, _dst):
        raise OSError("injected publication failure")

    monkeypatch.setattr(random_cache.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    assert artifact.read_bytes() == before
    conn = open_random_cache_artifact_readonly(artifact)
    try:
        assert read_random_cache_meta(conn)["build_id"] == first["build_id"]
    finally:
        conn.close()
    assert not list(tmp_path.glob(".random.db.tmp-*"))


def test_successful_publication_uses_sibling_temp_and_no_wal_sidecar(tmp_path: Path, monkeypatch) -> None:
    """Positive/negative: publication stays same-filesystem and never depends on WAL state."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    real_replace = random_cache.os.replace
    observed: dict[str, Path] = {}

    def capture_replace(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        observed["source"] = source_path
        observed["destination"] = destination_path
        assert source_path.parent == destination_path.parent == artifact.parent
        assert source_path.name.startswith(f".{artifact.name}.tmp-")
        assert not Path(f"{source_path}-wal").exists()
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(random_cache.os, "replace", capture_replace)
    rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    assert observed["destination"] == artifact
    assert not Path(f"{artifact}-wal").exists()
    conn = sqlite3.connect(artifact)
    try:
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "delete"
    finally:
        conn.close()

def test_build_failure_without_prior_final_leaves_no_authoritative_artifact(tmp_path: Path, monkeypatch) -> None:
    """Negative: first-generation build failure leaves only provider-unavailable state."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)

    def fail_population(*_args, **_kwargs):
        raise RuntimeError("injected first build failure")

    monkeypatch.setattr(random_cache, "populate_random_cache", fail_population)
    with pytest.raises(RuntimeError, match="first build failure"):
        rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    assert not artifact.exists()
    assert not list(tmp_path.glob(".random.db.tmp-*"))
    with pytest.raises(RandomCacheUnavailable):
        open_random_cache_artifact_readonly(artifact)


def test_validation_failure_without_prior_final_leaves_no_authoritative_artifact(tmp_path: Path, monkeypatch) -> None:
    """Negative: validation failure cannot publish an incomplete first generation."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    original = random_cache.open_random_cache_artifact_readonly

    def reject_temp(path: Path):
        if path != artifact:
            raise RandomCacheUnavailable("injected first validation failure")
        return original(path)

    monkeypatch.setattr(random_cache, "open_random_cache_artifact_readonly", reject_temp)
    with pytest.raises(RandomCacheUnavailable, match="first validation failure"):
        rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    assert not artifact.exists()
    assert not list(tmp_path.glob(".random.db.tmp-*"))



def test_runtime_rejects_artifact_with_extra_user_table(tmp_path: Path) -> None:
    """Positive/negative: exact artifact schema accepts builder output but rejects extra user tables."""
    canonical = tmp_path / "main.db"
    artifact = tmp_path / "random.db"
    _canonical(canonical)
    src = _source_connection(canonical)
    rebuild_random_cache(src, artifact, size=2, refresh=True)
    src.close()

    accepted = open_random_cache_artifact_readonly(artifact)
    accepted.close()

    writer = sqlite3.connect(artifact)
    writer.execute("CREATE TABLE videos(language TEXT, category TEXT)")
    writer.commit()
    writer.close()

    with pytest.raises(RandomCacheUnavailable, match="only generation metadata and persisted order"):
        open_random_cache_artifact_readonly(artifact)


def test_validator_rejects_wrong_v2_column_shape_and_duplicate_index_ids(tmp_path: Path) -> None:
    """Negative: v2 table names alone cannot bypass exact artifact/order validation."""
    extra_column = tmp_path / "extra-column.db"
    conn = sqlite3.connect(extra_column)
    conn.executescript(
        """
        CREATE TABLE random_cache_meta (singleton_id INTEGER, schema_version INTEGER, build_id TEXT, built_at TEXT);
        CREATE TABLE random_index_ids (position INTEGER, index_id INTEGER, language TEXT);
        INSERT INTO random_cache_meta VALUES (1, 2, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'x');
        INSERT INTO random_index_ids VALUES (1, 10, 'uk');
        """
    )
    conn.commit()
    conn.close()
    with pytest.raises(RandomCacheUnavailable, match="columns are incompatible"):
        open_random_cache_artifact_readonly(extra_column)

    duplicate_ids = tmp_path / "duplicate-ids.db"
    conn = sqlite3.connect(duplicate_ids)
    conn.executescript(
        """
        CREATE TABLE random_cache_meta (singleton_id INTEGER, schema_version INTEGER, build_id TEXT, built_at TEXT);
        CREATE TABLE random_index_ids (position INTEGER, index_id INTEGER);
        INSERT INTO random_cache_meta VALUES (1, 2, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'x');
        INSERT INTO random_index_ids VALUES (1, 10);
        INSERT INTO random_index_ids VALUES (2, 10);
        """
    )
    conn.commit()
    conn.close()
    with pytest.raises(RandomCacheUnavailable, match="index ids are not unique"):
        open_random_cache_artifact_readonly(duplicate_ids)


def test_validator_maps_malformed_schema_version_to_provider_unavailable(tmp_path: Path) -> None:
    """Positive/negative: numeric v2 metadata validates; non-numeric SQLite values fail controllably."""
    valid = tmp_path / "valid.db"
    conn = sqlite3.connect(valid)
    conn.row_factory = sqlite3.Row
    bootstrap_engine_random_cache_db(conn)
    conn.execute(
        "INSERT INTO random_cache_meta(singleton_id,schema_version,build_id,built_at) VALUES (1,2,?,'x')",
        ("c" * 32,),
    )
    conn.commit()
    conn.close()
    accepted = open_random_cache_artifact_readonly(valid)
    accepted.close()

    malformed = tmp_path / "bad-version.db"
    conn = sqlite3.connect(malformed)
    conn.executescript(
        """
        CREATE TABLE random_cache_meta (singleton_id INTEGER, schema_version INTEGER, build_id TEXT, built_at TEXT);
        CREATE TABLE random_index_ids (position INTEGER, index_id INTEGER);
        INSERT INTO random_cache_meta VALUES (1, 'not-an-int', 'dddddddddddddddddddddddddddddddd', 'x');
        """
    )
    conn.commit()
    conn.close()
    with pytest.raises(RandomCacheUnavailable, match="schema version is invalid"):
        open_random_cache_artifact_readonly(malformed)
