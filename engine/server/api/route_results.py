"""Framework-neutral result values for Engine API route boundaries.

Route modules use this tiny value object to carry the existing HTTP status and
JSON payload through service boundaries without reintroducing FastAPI or legacy
handler-shaped response objects into domain/service code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RouteResult:
    """Represent one Engine JSON response before FastAPI serialization.

    The type deliberately carries only status and payload. CORS headers,
    content type, JSON formatting, and FastAPI ``Response`` construction remain
    owned by the HTTP adapter boundary.
    """

    status: int
    payload: dict[str, Any]
