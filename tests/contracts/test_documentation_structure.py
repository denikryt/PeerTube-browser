"""Enforce the documentation ownership structure defined by project rules."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DOCS = {
    "ARCHITECTURE.md",
    "ARCHITECTURE_DIAGRAM.md",
    "PROJECT_MAP.md",
    "RUNNING.md",
    "HOW_IT_WORKS.md",
    "UPDATER.md",
}


def test_docs_directory_contains_only_owned_documents() -> None:
    """The docs directory must not retain competing Markdown owners."""
    actual = {
        path.relative_to(ROOT / "docs").as_posix()
        for path in (ROOT / "docs").rglob("*.md")
    }

    assert actual == EXPECTED_DOCS


def test_readme_remains_a_short_project_description() -> None:
    """The root README must remain a description instead of a second documentation hub."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert text.startswith("# PeerTube Browser\n")
    assert text.count("\n#") == 0
    assert len(text.splitlines()) <= 5


def test_component_readmes_do_not_duplicate_project_documentation() -> None:
    """Component directories must not introduce competing README documents."""
    duplicates = [
        path.relative_to(ROOT).as_posix()
        for path in [
            ROOT / "client/README.md",
            ROOT / "client/frontend/README.md",
            ROOT / "engine/server/README.md",
            ROOT / "engine/crawler/README.md",
        ]
        if path.exists()
    ]

    assert duplicates == []
