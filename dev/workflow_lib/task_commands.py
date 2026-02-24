"""Register task command routing for workflow CLI."""

from __future__ import annotations

import argparse
from argparse import Namespace

from .context import WorkflowContext
from .placeholders import run_not_implemented


def register_task_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register task router with placeholder task flow subcommands."""
    task_parser = subparsers.add_parser(
        "task",
        help="Task-level workflow commands.",
    )
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)

    preflight_parser = task_subparsers.add_parser(
        "preflight",
        help="Run task preflight checks before implementation.",
    )
    preflight_parser.add_argument("--id", required=True, help="Task ID.")
    preflight_parser.set_defaults(handler=_handle_task_preflight)

    validate_parser = task_subparsers.add_parser(
        "validate",
        help="Run task validation checks after implementation.",
    )
    validate_parser.add_argument("--id", required=True, help="Task ID.")
    validate_parser.add_argument("--run-checks", action="store_true", help="Run checks for changed paths.")
    validate_parser.set_defaults(handler=_handle_task_validate)


def _handle_task_preflight(args: Namespace, context: WorkflowContext) -> int:
    """Handle placeholder task preflight command."""
    return run_not_implemented("task.preflight", args, context)


def _handle_task_validate(args: Namespace, context: WorkflowContext) -> int:
    """Handle placeholder task validate command."""
    return run_not_implemented("task.validate", args, context)

