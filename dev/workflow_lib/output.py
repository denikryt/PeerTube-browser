"""Provide deterministic command output helpers."""

from __future__ import annotations

import json
from typing import Any


def emit_json(payload: dict[str, Any]) -> None:
    """Emit stable JSON output for workflow commands."""
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
