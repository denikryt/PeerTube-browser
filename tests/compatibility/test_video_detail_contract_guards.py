"""Static guards for video-detail ownership and temporary compatibility scope."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DETAIL_SOURCE = ROOT / "engine/crawler/src/video-detail.ts"
WORKER_SOURCE = ROOT / "engine/crawler/src/videos-worker.ts"
GENERATION_SOURCES = [
    ROOT / "engine/crawler/src/db/videos.ts",
    ROOT / "engine/server/db/jobs/updater/staging.py",
    ROOT / "engine/server/db/jobs/sync-whitelist.py",
]
SEMANTIC_SOURCE_ROOTS = [
    ROOT / "engine/crawler/src",
    ROOT / "engine/crawler/test",
    ROOT / "engine/server/db/jobs/updater",
    ROOT / "tests/jobs",
    ROOT / "tests/engine_data",
]


def test_video_detail_boundary_has_one_request_owner_and_no_persistence_dependency() -> None:
    """The canonical detail module owns the request but cannot write crawler state."""
    text = DETAIL_SOURCE.read_text(encoding="utf-8")

    assert text.count("async function fetchVideoDetailInternal") == 1
    assert "fetchJsonWithRetry<unknown>" in text
    assert "VideoStore" not in text
    assert "better-sqlite3" not in text
    assert "updateVideoInvalid" not in text


def test_temporary_video_compatibility_markers_have_exact_bounded_inventory() -> None:
    """Planned shims remain searchable while permanent role guards stay unmarked."""
    detail_text = DETAIL_SOURCE.read_text(encoding="utf-8")
    worker_text = WORKER_SOURCE.read_text(encoding="utf-8")
    generation_text = "\n".join(path.read_text(encoding="utf-8") for path in GENERATION_SOURCES)

    assert detail_text.count("TODO(nodeforge-video-detail-result)") == 1
    assert worker_text.count("TODO(nodeforge-video-detail-result)") == 1
    assert worker_text.count("TODO(nodeforge-existing-video-availability-owner)") == 0
    assert generation_text.count("TODO(nodeforge-video-availability-generation-cutover)") == 3
    assert "standalone_full_sync_source" not in generation_text


def test_video_implementation_sources_use_semantic_names_instead_of_numbered_phase_labels() -> None:
    """Implementation/test identifiers and comments must use domain semantics."""
    forbidden = re.compile("Stage" + r" [0-9]+")
    matches: list[str] = []
    for root in SEMANTIC_SOURCE_ROOTS:
        if root.is_file():
            paths = [root]
        else:
            paths = [path for path in root.rglob("*") if path.suffix in {".py", ".ts"}]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if forbidden.search(text):
                matches.append(str(path.relative_to(ROOT)))

    assert matches == []


def test_operational_writer_evidence_does_not_enter_canonical_schema() -> None:
    """Lifecycle evidence stays operational rather than becoming canonical columns."""
    schema = (ROOT / "engine/crawler/schema.sql").read_text(encoding="utf-8")

    assert "video_availability_semantics" not in schema
    assert "video_corpus_role" not in schema
    assert "updater_staging_delta" not in schema


def test_maintenance_has_no_canonical_writer_api() -> None:
    """Diagnostics cannot reintroduce an existing-row availability writer."""
    store = (ROOT / "engine/crawler/src/db/videos.ts").read_text()
    assert "updateVideoInvalid" not in store
    assert "updateVideoInvalid" not in WORKER_SOURCE.read_text()
    method = store.split("updateVideoError(", 1)[1].split("interface StoredVideoIdentity", 1)[0]
    assert "invalid_reason" not in method and "invalid_at" not in method
