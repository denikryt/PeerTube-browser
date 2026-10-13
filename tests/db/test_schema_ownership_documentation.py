"""Verify current data-store ownership remains documented in one place."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "HOW_IT_WORKS.md"


def test_schema_ownership_documentation_contains_required_sections() -> None:
    """The internals document must cover every current database family."""
    text = DOC.read_text(encoding="utf-8")

    for heading in [
        "Client Database",
        "Crawler Database",
        "Canonical Engine Database",
        "Derived Artifacts",
    ]:
        assert heading in text


def test_schema_ownership_documentation_names_current_data_owners() -> None:
    """The internals document must identify current schema and artifact owners."""
    text = DOC.read_text(encoding="utf-8")

    for phrase in [
        "client/backend/db/bootstrap.py",
        "engine/crawler/schema.sql",
        "engine/server/db/whitelist.db",
        "video_facets_snapshot",
        "whitelist-video-embeddings.faiss",
        "similarity-cache.db",
        "random-cache.db",
    ]:
        assert phrase in text
