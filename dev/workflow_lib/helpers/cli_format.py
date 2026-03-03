"""Provide CLI format runtime helpers for workflow commands."""

from __future__ import annotations

import argparse


class CompactHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    """Represent compact help formatter behavior."""

    _wrap_width = 72

    def __init__(self, prog: str) -> None:
        """Initialize the instance."""
        super().__init__(prog, max_help_position=18, width=self._wrap_width)

    def _format_action(self, action: argparse.Action) -> str:
        """Format one parser action with compact wrapped help text."""
        if action.help is argparse.SUPPRESS:
            return ""
        header = self._format_action_invocation(action)
        help_text = self._expand_help(action)
        if not help_text:
            return f"{header}\n"
        lines: list[str] = []
        for raw_line in help_text.splitlines():
            if not raw_line.strip():
                lines.append("")
                continue
            lines.extend(self._split_lines(raw_line, self._wrap_width - 2))
        body = "\n  ".join(lines)
        return f"{header}\n  {body}\n\n"

    def _format_text(self, text: str) -> str:
        """Format free text blocks such as description and epilog."""
        if not text:
            return ""
        paragraphs: list[str] = []
        for raw_line in text.splitlines():
            if not raw_line.strip():
                paragraphs.append("")
                continue
            paragraphs.extend(self._split_lines(raw_line, self._wrap_width))
        return "\n".join(paragraphs) + "\n"
