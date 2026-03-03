"""Parse markdown draft files used by workflow create commands."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import WorkflowCommandError


HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.*\S)\s*$", re.MULTILINE)


def parse_feature_issue_template(file_path: Path) -> dict[str, Any]:
    """Parse a markdown draft file into title/description fields plus non-fatal warnings."""
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise WorkflowCommandError(
            f"Input file not found: {file_path}. Ensure the file exists before re-running.",
            exit_code=4,
        ) from error
    except OSError as error:
        raise WorkflowCommandError(
            f"Failed to read input file {file_path}: {error}. Ensure the file is readable before re-running.",
            exit_code=4,
        ) from error

    matches = list(HEADING_PATTERN.finditer(raw_text))
    if not matches:
        raise WorkflowCommandError(
            f"No headings detected in {file_path}. Expected at least one heading for title. "
            "Format: # Title followed by content.",
            exit_code=4,
        )

    title = matches[0].group("text").strip()
    if not title:
        raise WorkflowCommandError(
            "Title heading is empty. Provide text after the first heading, e.g., '# My Title'",
            exit_code=4,
        )

    description_start = matches[0].end()
    description_end = matches[1].start() if len(matches) > 1 else len(raw_text)
    description = raw_text[description_start:description_end].strip()
    warnings: list[str] = []
    if not description:
        warnings.append(
            f"Description section is empty in {file_path}. Continuing with an empty description."
        )

    return {
        "title": title,
        "description": description,
        "warnings": warnings,
    }
