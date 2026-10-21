"""Documentation checks for the current FastAPI runtime contracts."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_internals_document_records_current_http_runtime_contracts() -> None:
    """The internals document must preserve the active HTTP behavior."""
    text = (ROOT / "docs" / "HOW_IT_WORKS.md").read_text()
    required = [
        "preserves allowed upstream status, body, and content type",
        "return `204` for preflight requests",
        "`client_ip:path`",
        "invalid JSON and request-size errors",
        "`ENGINE_INGEST_MODE=bridge`",
        "compatible FAISS index",
    ]
    for phrase in required:
        assert phrase in text
