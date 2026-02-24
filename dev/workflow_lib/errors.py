"""Define workflow CLI specific error types."""

from __future__ import annotations


class WorkflowCommandError(Exception):
    """Represent a command-level workflow execution error."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        """Initialize the command error."""
        super().__init__(message)
        self.exit_code = exit_code

