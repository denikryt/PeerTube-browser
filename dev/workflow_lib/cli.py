"""Build and execute the workflow CLI command tree."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .confirm_commands import register_confirm_router
from .context import WorkflowContext, build_default_context
from .errors import WorkflowCommandError
from .feature_commands import register_feature_router, register_plan_router
from .task_commands import register_task_router
from .validate_commands import register_validate_router


class WorkflowArgumentParser(argparse.ArgumentParser):
    """Provide deterministic parser error output and exit code."""

    def error(self, message: str) -> None:
        """Print deterministic usage+error text for invalid args."""
        self.print_usage(sys.stderr)
        self.exit(2, f"workflow error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level workflow parser with all command routers."""
    parser = WorkflowArgumentParser(
        prog="workflow",
        description="Workflow automation CLI for repository planning/execution flow.",
    )
    subparsers = parser.add_subparsers(dest="command_group", required=True)
    register_feature_router(subparsers)
    register_plan_router(subparsers)
    register_task_router(subparsers)
    register_confirm_router(subparsers)
    register_validate_router(subparsers)
    return parser


def main(argv: Sequence[str] | None = None, context: WorkflowContext | None = None) -> int:
    """Run workflow CLI command dispatch."""
    parser = build_parser()
    args = parser.parse_args(argv)
    active_context = context or build_default_context()
    try:
        return int(args.handler(args, active_context))
    except WorkflowCommandError as error:
        print(f"workflow command error: {error}", file=sys.stderr)
        return int(error.exit_code)
