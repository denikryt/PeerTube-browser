"""Provide structured Engine logging helpers with mode-tagged JSON events."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from request_context import fetch_request_id


SUPPORTED_LOG_MODES = ("focused", "verbose")
_ALL_MODES = list(SUPPORTED_LOG_MODES)
_PREFIX_RE = re.compile(r"^\[(?P<scope>[^\]]+)\]\s*(?P<body>.*)$")
_REQUEST_PREFIX_RE = re.compile(r"^\[[^\]]+\]\[(?P<request_id>[^\]]+)\]")
_LEADING_BLOCKS_RE = re.compile(r"^(?:\[[^\]]+\])+\s*")


@dataclass(frozen=True)
class _EventRule:
    """Map a message needle to stable event and view modes."""

    needle: str
    event: str
    modes: tuple[str, ...]


_EVENT_RULES = (
    _EventRule("[access.start]", "access.start", ("focused", "verbose")),
    _EventRule("[access]", "access", ("focused", "verbose")),
    _EventRule("[service] lifecycle", "service.lifecycle", ("focused", "verbose")),
    _EventRule(
        "[recommendations] layer timing:",
        "recommendations.layer_timing",
        ("focused", "verbose"),
    ),
    _EventRule(
        "[recommendations] profile=",
        "recommendations.profile",
        ("focused", "verbose"),
    ),
    _EventRule(
        "[recommendations] exploit cache seed batch",
        "recommendations.exploit_seed_batch",
        ("focused", "verbose"),
    ),
    _EventRule(
        "[recommendations] incoming likes body=",
        "recommendations.incoming_likes_body",
        ("focused", "verbose"),
    ),
    _EventRule(
        "[similar-cache] hit source=",
        "similarity.cache_hit",
        ("focused", "verbose"),
    ),
    _EventRule(
        "[similar-server] candidates=",
        "similarity.candidates",
        ("focused", "verbose"),
    ),
    _EventRule(
        "] done count=",
        "similarity.request_done",
        ("focused", "verbose"),
    ),
)


def normalize_log_mode(mode: str | None) -> str:
    """Normalize mode names and fail safely to ``verbose``."""
    raw = (mode or "").strip().lower()
    if raw in SUPPORTED_LOG_MODES:
        return raw
    return "verbose"


def payload_visible_in_mode(payload: dict[str, Any], mode: str | None) -> bool:
    """Return True when a structured log payload should be visible in mode."""
    selected = normalize_log_mode(mode)
    level = str(payload.get("level") or "").upper()
    if level in {"WARNING", "ERROR", "CRITICAL"}:
        return True
    modes = payload.get("modes")
    if not isinstance(modes, list) or not modes:
        return selected == "verbose"
    return selected in modes


def _extract_request_id(record: logging.LogRecord, message: str) -> str | None:
    """Resolve request id from record extras, message prefix, or request context."""
    from_extra = getattr(record, "request_id", None)
    if isinstance(from_extra, str) and from_extra.strip():
        return from_extra.strip()

    matched = _REQUEST_PREFIX_RE.match(message)
    if matched:
        value = matched.group("request_id").strip()
        if value:
            return value

    return fetch_request_id()


def _extract_fields(message: str) -> dict[str, str]:
    """Extract best-effort ``key=value`` tokens from message text."""
    cleaned = _LEADING_BLOCKS_RE.sub("", message).strip()
    if not cleaned:
        return {}

    fields: dict[str, str] = {}
    for token in cleaned.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip()
        value = value.strip().strip(",")
        if not key:
            continue
        fields[key] = value
    return fields


def _normalize_incoming_likes_context(
    raw_body: str | None,
) -> dict[str, Any] | None:
    """Parse and normalize incoming likes payload from message body token."""
    if not raw_body:
        return None
    try:
        parsed = json.loads(raw_body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None

    raw_likes = parsed.get("likes")
    likes: list[dict[str, str | None]] = []
    if isinstance(raw_likes, list):
        for entry in raw_likes:
            if not isinstance(entry, dict):
                continue
            likes.append(
                {
                    "uuid": str(entry.get("uuid") or "").strip() or None,
                    "host": str(entry.get("host") or "").strip() or None,
                }
            )

    return {
        "likes_count": len(likes),
        "likes": likes,
        "user_id": parsed.get("user_id"),
        "mode": parsed.get("mode"),
    }


def _derive_event_name(message: str) -> str:
    """Derive a fallback event name from message prefix."""
    matched = _PREFIX_RE.match(message)
    if not matched:
        return "engine.log"
    scope = matched.group("scope").strip().lower().replace("-", "_")
    if not scope:
        return "engine.log"
    return f"{scope}.info"


def _classify_event(message: str, levelno: int) -> tuple[str, list[str]]:
    """Classify a log event and assign target viewing modes."""
    if levelno >= logging.WARNING:
        return _derive_event_name(message), _ALL_MODES

    for rule in _EVENT_RULES:
        if rule.needle in message:
            return rule.event, list(rule.modes)

    return _derive_event_name(message), ["verbose"]


class EngineJsonFormatter(logging.Formatter):
    """Render engine log records as JSON objects with mode tags."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON line."""
        message = record.getMessage()
        event, modes = _classify_event(message, record.levelno)
        request_id = _extract_request_id(record, message)
        fields = _extract_fields(message)

        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": event,
            "message": message,
            "modes": modes,
        }
        if request_id:
            payload["request_id"] = request_id
        if event == "recommendations.incoming_likes_body":
            incoming_context = _normalize_incoming_likes_context(fields.get("body"))
            payload["message"] = "[recommendations] incoming likes"
            if incoming_context is not None:
                payload["context"] = incoming_context
            elif fields:
                payload["context"] = fields
        elif event == "service.lifecycle":
            payload.pop("message", None)
            payload["context"] = fields
        elif fields:
            payload["context"] = fields
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_engine_logging(profile: str) -> str:
    """Configure root logger with JSON formatter and return normalized mode hint."""
    selected = normalize_log_mode(profile)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(EngineJsonFormatter())
    root_logger.addHandler(handler)
    return selected
