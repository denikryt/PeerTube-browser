"""Verify schema ownership documentation stays present and scoped."""
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
        "Removed transitional schema wrappers",
        "Future ownership by stage",
    ]:
        assert heading in text


def test_schema_ownership_documentation_records_removed_wrapper_decisions() -> None:
    """The document must record the removed transitional wrapper decisions."""
    text = DOC.read_text(encoding="utf-8")

    for phrase in [
        "Decision: remove client/backend/lib/users_store.py::ensure_user_schema",
        "Decision: remove engine/server/data/interaction_events.py::ensure_interaction_event_schema",
        "Decision: remove engine/server/data/channels.py::ensure_channels_indexes",
        "Decision: remove engine/server/data/similarity_cache.py::ensure_similarity_schema",
        "Implementation action:",
        "Tests:",
    ]:
        assert phrase in text
