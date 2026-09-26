"""Documentation checks for Stage 10 framework compatibility decisions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_framework_compatibility_document_records_required_decisions() -> None:
    """Framework compatibility decisions must be explicit and test-linked."""
    text = (ROOT / "docs" / "FRAMEWORK_COMPATIBILITY.md").read_text()
    required = [
        "server.py entrypoint paths remain stable",
        "CORS and OPTIONS behavior is preserved",
        "Rate-limit keys are preserved",
        "Request-size and invalid JSON errors are preserved",
        "Client read proxy byte/status/content-type preservation is preserved",
        "/videos/{id}/similar path-id injection is preserved",
        "/internal/events/ingest mode gate is preserved",
        "FAISS startup prerequisite is unchanged",
        "Pydantic/OpenAPI schema redesign is deferred",
    ]
    for phrase in required:
        assert phrase in text
    assert text.count("Decision:") >= len(required)
    assert "Implementation action:" in text
    assert "Tests:" in text
