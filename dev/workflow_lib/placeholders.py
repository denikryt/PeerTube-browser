"""Provide placeholder handlers for not-yet-implemented commands."""

from __future__ import annotations

from argparse import Namespace

from .context import WorkflowContext
from .output import emit_json


def run_not_implemented(command: str, _args: Namespace, _context: WorkflowContext) -> int:
    """Report a deterministic placeholder response for a command."""
    emit_json(
        {
            "command": command,
            "implemented": False,
            "status": "not-implemented",
        }
    )
    return 3

