"""Verify Stage 6 schema ownership documentation stays present and scoped."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "SCHEMA_OWNERSHIP.md"


def test_schema_ownership_documentation_contains_required_sections() -> None:
    """The schema ownership document must cover every current DB family."""
    text = DOC.read_text(encoding="utf-8")

    for heading in [
        "Client users DB",
        "Crawler raw crawl DB",
        "Engine main dataset DB",
        "Engine runtime tables and indexes",
        "Engine similarity cache DB",
        "Engine random cache DB",
        "Engine derived artifacts",
        "Compatibility wrappers",
        "Future ownership by stage",
    ]:
        assert heading in text


def test_schema_ownership_documentation_records_compatibility_decisions() -> None:
    """Stage 6 compatibility decisions must be explicit and test-linked."""
    text = DOC.read_text(encoding="utf-8")

    for phrase in [
        "Decision: keep client/backend/lib/users_store.py::ensure_user_schema",
        "Decision: keep engine/server/data/interaction_events.py::ensure_interaction_event_schema",
        "Decision: keep crawler schema ownership in engine/crawler/schema.sql",
        "Implementation action:",
        "Tests:",
        "Removal condition:",
    ]:
        assert phrase in text
