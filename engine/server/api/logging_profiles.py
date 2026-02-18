"""Provide logging profile runtime helpers."""

from __future__ import annotations

import logging


_FOCUSED_INFO_PATTERNS = (
    "[access]",
    "[recommendations] layer timing:",
    "[recommendations] profile=",
    "[recommendations] exploit cache seed batch",
    "[similar-cache] hit source=",
    "[similar-server] candidates=",
)


class EngineLogProfileFilter(logging.Filter):
    """Filter INFO logs according to selected server logging profile."""

    def __init__(self, profile: str) -> None:
        """Initialize the instance."""
        super().__init__()
        self.profile = profile

    def filter(self, record: logging.LogRecord) -> bool:
        """Allow or suppress a record for current profile."""
        if record.levelno >= logging.WARNING:
            return True
        if self.profile != "focused":
            return True
        message = record.getMessage()
        for pattern in _FOCUSED_INFO_PATTERNS:
            if pattern in message:
                return True
        return False


def configure_engine_logging(profile: str) -> str:
    """Configure root logger for Engine server and return active profile."""
    selected = (profile or "verbose").strip().lower()
    if selected not in {"verbose", "focused"}:
        selected = "verbose"

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(EngineLogProfileFilter(selected))
    root_logger.addHandler(handler)
    return selected
