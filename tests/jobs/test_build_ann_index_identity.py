"""Tests for ANN build input identity and artifact metadata validation."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
JOB = ROOT / "engine" / "server" / "db" / "jobs" / "build-ann-index.py"
ANN_ARTIFACT = ROOT / "engine" / "server" / "data" / "ann_artifact.py"


def _install_fake_faiss() -> None:
    """Install the tiny FAISS surface needed while importing scripts."""
    fake = types.SimpleNamespace(
        METRIC_INNER_PRODUCT=0,
        IO_FLAG_MMAP=1,
        IO_FLAG_READ_ONLY=2,
        normalize_L2=lambda vectors: None,
        Index=object,
        IndexFlatIP=lambda dim: object(),
        IndexIVFPQ=lambda *args, **kwargs: object(),
        IndexIDMap2=lambda index: index,
        read_index=lambda *args, **kwargs: object(),
        write_index=lambda *args, **kwargs: None,
    )
    sys.modules.setdefault("faiss", fake)


def _load(path: Path, name: str) -> Any:
    """Load a script module with a hyphenated file name for behavior tests."""
    _install_fake_faiss()
    for name in ["db.bootstrap", "db"]:
        sys.modules.pop(name, None)
    # Force Engine server paths ahead of any client/backend package named `db`.
    for extra in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
        value = str(extra)
        while value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ann_source_db() -> sqlite3.Connection:
    """Create a minimal ANN source DB with one active and one inactive mapping."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE videos (video_id TEXT, instance_domain TEXT, PRIMARY KEY(video_id, instance_domain));
        CREATE TABLE video_embeddings (
          video_id TEXT,
          instance_domain TEXT,
          embedding BLOB,
          embedding_dim INTEGER,
          model_name TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_index_ids (
          index_id INTEGER PRIMARY KEY AUTOINCREMENT,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          retired_at INTEGER,
          retired_reason TEXT,
          UNIQUE(video_id, instance_domain)
        );
        """
    )
    for index_id, video_id, active in [(50, "v-active", 1), (60, "v-inactive", 0)]:
        blob = np.array([1.0, 0.0], dtype=np.float32).tobytes()
        conn.execute("INSERT INTO videos VALUES (?, 'h1')", (video_id,))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'h1', ?, 2, 'm')", (video_id, blob))
        conn.execute(
            """
            INSERT INTO video_index_ids (index_id, video_id, instance_domain, is_active, created_at, updated_at)
            VALUES (?, ?, 'h1', ?, 1, 1)
            """,
            (index_id, video_id, active),
        )
    return conn


def test_ann_build_iterates_active_index_ids_not_embedding_rowids() -> None:
    """Build input must expose `video_index_ids.index_id` as FAISS ids."""
    mod = _load(JOB, "build_ann_index_job")
    conn = _ann_source_db()
    query = """
        SELECT vii.index_id, e.embedding, e.embedding_dim
        FROM video_index_ids vii
        JOIN video_embeddings e
          ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
        JOIN videos v
          ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
        WHERE vii.is_active = 1
        """

    batches = list(mod.iter_embeddings(conn, query, (), 2, 100))

    assert len(batches) == 1
    assert [row.index_id for row in batches[0]] == [50]


def test_faiss_metadata_rejects_old_rowid_id_source(tmp_path: Path) -> None:
    """Runtime loading must fail before treating old rowid ids as stable index ids."""
    artifact = _load(ANN_ARTIFACT, "engine_ann_artifact_for_meta_test")
    index_path = tmp_path / "ann.index"
    index_path.write_bytes(b"fake")
    index_path.with_name(index_path.name + ".json").write_text(
        json.dumps({"schema_version": 1, "id_source": "video_embeddings.rowid"}),
        encoding="utf-8",
    )

    try:
        artifact.validate_faiss_artifact_metadata(index_path)
    except RuntimeError as exc:
        assert "Incompatible FAISS index metadata" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("old FAISS metadata was accepted")


def test_faiss_metadata_accepts_stable_index_id_source(tmp_path: Path) -> None:
    """Runtime loading must accept metadata produced by the migrated build job."""
    artifact = _load(ANN_ARTIFACT, "engine_ann_artifact_for_meta_ok_test")
    index_path = tmp_path / "ann.index"
    index_path.write_bytes(b"fake")
    index_path.with_name(index_path.name + ".json").write_text(
        json.dumps({"schema_version": 2, "id_source": "video_index_ids.index_id"}),
        encoding="utf-8",
    )

    artifact.validate_faiss_artifact_metadata(index_path)
