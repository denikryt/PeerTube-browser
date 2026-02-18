"""Provide cli format runtime helpers."""

from __future__ import annotations

import argparse


class CompactHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    """Represent compact help formatter behavior."""
    _wrap_width = 72

    def __init__(self, prog: str) -> None:
        """Initialize the instance."""
        super().__init__(prog, max_help_position=18, width=self._wrap_width)

    def _format_action(self, action: argparse.Action) -> str:
        """Handle format action."""
        if action.help is argparse.SUPPRESS:
            return ""
        header = self._format_action_invocation(action)
        help_text = self._expand_help(action)
        if not help_text:
            return f"{header}\n"
        lines = self._split_lines(help_text, self._wrap_width - 2)
        body = "\n  ".join(lines)
        return f"{header}\n  {body}\n\n"

    def _format_text(self, text: str) -> str:
        """Handle format text."""
        if not text:
            return ""
        lines = self._split_lines(text, self._wrap_width)
        return "\n".join(lines) + "\n"
