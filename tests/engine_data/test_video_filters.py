"""Regression tests for the shared Engine video-filter semantics."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

import pytest

from engine.server.data.video_filters import VideoFilters, build_video_filter_sql, matches_video_filters


def _conn() -> sqlite3.Connection:
    """Create a row-aware minimal canonical videos fixture."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE videos (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          language TEXT,
          category TEXT,
          tags_json TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_tags (
          tag TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          PRIMARY KEY(tag, video_id, instance_domain)
        ) WITHOUT ROWID
        """
    )
    conn.executemany(
        "INSERT INTO videos VALUES (?, ?, ?, ?, ?)",
        [
            ("uk-linux", "video.example.org", "uk", "Education", '["Linux", "fediverse"]'),
            ("unknown", "video.example.org", None, "Music", '["music"]'),
            ("blank-language", "other.example.org", "   ", "education", '["LINUX", "linux"]'),
            ("bad-tags", "other.example.org", "en", "Education", "not-json"),
            ("linuxmint", "video.example.org", "uk", "Education", '["linuxmint"]'),
        ],
    )
    conn.executemany(
        "INSERT INTO video_tags(tag,video_id,instance_domain) VALUES (?,?,?)",
        [
            ("linux", "uk-linux", "video.example.org"),
            ("fediverse", "uk-linux", "video.example.org"),
            ("music", "unknown", "video.example.org"),
            ("linux", "blank-language", "other.example.org"),
            ("linuxmint", "linuxmint", "video.example.org"),
        ],
    )
    return conn


def _sql_ids(filters: VideoFilters) -> list[str]:
    """Evaluate the production SQL predicate against the fixture."""
    conn = _conn()
    clause, params = build_video_filter_sql("v", filters)
    rows = conn.execute(
        f"SELECT v.* FROM videos v WHERE 1=1 {clause} ORDER BY video_id", params
    ).fetchall()
    return [str(row["video_id"]) for row in rows]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (VideoFilters(language="uk"), ["linuxmint", "uk-linux"]),
        (VideoFilters(language="_unknown"), ["blank-language", "unknown"]),
        (VideoFilters(category="education"), ["bad-tags", "blank-language", "linuxmint", "uk-linux"]),
        (VideoFilters(tag="linux"), ["blank-language", "uk-linux"]),
        (VideoFilters(instance="video.example.org"), ["linuxmint", "uk-linux", "unknown"]),
        (
            VideoFilters(language="uk", category="education", tag="linux", instance="video.example.org"),
            ["uk-linux"],
        ),
    ],
)
def test_sql_filters_accept_only_matching_rows(filters: VideoFilters, expected: list[str]) -> None:
    """Positive path: every supported dimension and AND-combination selects matching rows."""
    assert _sql_ids(filters) == expected


def test_tag_filter_rejects_substrings_and_malformed_json() -> None:
    """Negative path: exact tag membership cannot match serialized substrings or invalid JSON."""
    assert _sql_ids(VideoFilters(tag="linux")) == ["blank-language", "uk-linux"]
    assert "linuxmint" not in _sql_ids(VideoFilters(tag="linux"))
    assert "bad-tags" not in _sql_ids(VideoFilters(tag="linux"))


def test_row_matcher_matches_sql_semantics_for_dirty_metadata() -> None:
    """Positive/negative row checks use the same normalization as the SQL boundary."""
    conn = _conn()
    rows = [dict(row) for row in conn.execute("SELECT * FROM videos ORDER BY video_id")]
    filters = VideoFilters(language="_unknown", category="education", tag="linux", instance="other.example.org")
    matched = [row["video_id"] for row in rows if matches_video_filters(row, filters)]
    assert matched == ["blank-language"]
    assert not matches_video_filters(rows[0], VideoFilters(tag="linux"))  # malformed JSON row


def test_tag_filter_and_row_matcher_reject_non_array_json_shapes() -> None:
    """Only textual members of a JSON array can satisfy the tag contract."""
    conn = _conn()
    conn.executemany(
        "INSERT INTO videos VALUES (?, ?, ?, ?, ?)",
        [
            ("array-tag", "shape.example", "en", "Other", '["linux"]'),
            ("object-tag", "shape.example", "en", "Other", '{"x":"linux"}'),
            ("string-tag", "shape.example", "en", "Other", '"linux"'),
            ("number-tag", "shape.example", "en", "Other", '123'),
            ("json-null-tag", "shape.example", "en", "Other", 'null'),
            ("malformed-tag", "shape.example", "en", "Other", '{bad'),
        ],
    )
    conn.execute(
        "INSERT INTO video_tags(tag,video_id,instance_domain) VALUES ('linux','array-tag','shape.example')"
    )
    clause, params = build_video_filter_sql("v", VideoFilters(tag="linux"))
    sql_ids = [
        str(row["video_id"])
        for row in conn.execute(
            f"SELECT v.* FROM videos v WHERE v.instance_domain='shape.example' {clause} ORDER BY video_id",
            params,
        ).fetchall()
    ]
    assert sql_ids == ["array-tag"]

    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM videos WHERE instance_domain='shape.example' ORDER BY video_id"
        ).fetchall()
    ]
    row_ids = [row["video_id"] for row in rows if matches_video_filters(row, VideoFilters(tag="linux"))]
    assert row_ids == ["array-tag"]

def test_unknown_language_normalization_preserves_blank_and_null_only() -> None:
    """Unknown language accepts NULL/blank values but rejects normalized real codes."""
    assert _sql_ids(VideoFilters(language="_unknown")) == ["blank-language", "unknown"]
    assert "uk-linux" not in _sql_ids(VideoFilters(language="_unknown"))


def test_instance_filter_preserves_case_and_whitespace_normalization() -> None:
    """Instance matching stays normalized because stored legacy hosts are not constrained."""
    conn = _conn()
    conn.execute(
        "INSERT INTO videos VALUES (?, ?, ?, ?, ?)",
        ("mixed-host", "  VIDEO.Example.Org  ", "en", "Music", '[]'),
    )
    clause, params = build_video_filter_sql("v", VideoFilters(instance="video.example.org"))
    ids = [
        str(row["video_id"])
        for row in conn.execute(
            f"SELECT v.* FROM videos v WHERE 1=1 {clause} ORDER BY video_id", params
        ).fetchall()
    ]
    assert "mixed-host" in ids
    assert "bad-tags" not in ids


def test_tag_filter_uses_trusted_prepared_schema_and_rejects_sql_namespace_input() -> None:
    """Positive/negative: tag membership can target canonical attachment but rejects arbitrary schema names."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        ATTACH DATABASE ':memory:' AS canonical;
        CREATE TABLE canonical.videos(video_id TEXT, instance_domain TEXT, language TEXT, category TEXT, tags_json TEXT);
        CREATE TABLE canonical.video_tags(
          tag TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL,
          PRIMARY KEY(tag, video_id, instance_domain)
        ) WITHOUT ROWID;
        INSERT INTO canonical.videos VALUES ('v1','example.org','en','Education','not-json');
        INSERT INTO canonical.video_tags VALUES ('linux','v1','example.org');
        """
    )
    clause, params = build_video_filter_sql("v", VideoFilters(tag="linux"), schema="canonical")
    ids = [
        row[0]
        for row in conn.execute(
            f"SELECT v.video_id FROM canonical.videos v WHERE 1=1 {clause}", params
        )
    ]
    assert ids == ["v1"]
    assert "json_each" not in clause

    with pytest.raises(ValueError, match="Unsupported video filter schema"):
        build_video_filter_sql("v", VideoFilters(tag="linux"), schema="main; DROP TABLE videos")
