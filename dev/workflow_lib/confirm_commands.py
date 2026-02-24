"""Register confirm command routing for workflow CLI."""

from __future__ import annotations

import argparse
from argparse import Namespace

from .context import WorkflowContext
from .placeholders import run_not_implemented


def register_confirm_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register confirm router with completion target subcommands."""
    confirm_parser = subparsers.add_parser(
        "confirm",
        help="Completion confirmation workflow commands.",
    )
    confirm_subparsers = confirm_parser.add_subparsers(dest="confirm_target", required=True)

    _register_confirm_target(confirm_subparsers, "task", "Confirm one task completion.")
    _register_confirm_target(confirm_subparsers, "issue", "Confirm one issue completion.")
    _register_confirm_target(confirm_subparsers, "feature", "Confirm one feature completion.")
    _register_confirm_target(
        confirm_subparsers,
        "standalone-issue",
        "Confirm one standalone issue completion.",
    )


def _register_confirm_target(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    target: str,
    help_text: str,
) -> None:
    """Register a single confirm target parser."""
    parser = subparsers.add_parser(target, help=help_text)
    parser.add_argument("--id", required=True, help=f"{target} identifier.")
    parser.set_defaults(handler=_handle_confirm)


def _handle_confirm(args: Namespace, context: WorkflowContext) -> int:
    """Handle placeholder confirm command for any target."""
    command_name = f"confirm.{args.confirm_target}"
    return run_not_implemented(command_name, args, context)

