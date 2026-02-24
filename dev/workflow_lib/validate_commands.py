"""Register repository validation command routing for workflow CLI."""

from __future__ import annotations

import argparse
from argparse import Namespace

from .context import WorkflowContext
from .placeholders import run_not_implemented


def register_validate_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register validate router with scope gates."""
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validation commands for tracking and repository gates.",
    )
    validate_parser.add_argument(
        "--scope",
        choices=["tracking", "repo"],
        required=True,
        help="Validation scope to execute.",
    )
    validate_parser.add_argument("--feature", help="Optional feature ID filter.")
    validate_parser.add_argument("--strict", action="store_true", help="Enable strict validation mode.")
    validate_parser.set_defaults(handler=_handle_validate)


def _handle_validate(args: Namespace, context: WorkflowContext) -> int:
    """Handle placeholder validate command."""
    return run_not_implemented("validate.run", args, context)

