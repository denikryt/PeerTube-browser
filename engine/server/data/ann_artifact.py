"""Validate ANN artifact metadata before loading FAISS index files."""

from __future__ import annotations

import json
from pathlib import Path

EXPECTED_ANN_SCHEMA_VERSION = 2
EXPECTED_ANN_ID_SOURCE = "video_index_ids.index_id"


def validate_faiss_artifact_metadata(index_path: Path) -> None:
    """Reject stale FAISS artifacts whose ids are not stable video index ids.

    FAISS stores opaque int64 ids. After the stable-index migration, those ids
    must mean `video_index_ids.index_id`; loading old rowid artifacts would be
    silent data corruption rather than a clean startup failure.
    """
    meta_path = index_path.with_name(index_path.name + ".json")
    if not meta_path.exists():
        raise RuntimeError(
            f"Missing FAISS metadata {meta_path}; rebuild the ANN index with build-ann-index.py"
        )
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid FAISS metadata {meta_path}: {exc}") from exc
    if (
        metadata.get("schema_version") != EXPECTED_ANN_SCHEMA_VERSION
        or metadata.get("id_source") != EXPECTED_ANN_ID_SOURCE
    ):
        raise RuntimeError(
            "Incompatible FAISS index metadata; expected schema_version=2 and "
            "id_source=video_index_ids.index_id. Rebuild the ANN index."
        )
