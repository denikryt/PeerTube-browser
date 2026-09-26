"""Shared lightweight result types for Client backend service boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServiceResult:
    """HTTP-neutral JSON result returned by Client backend services."""

    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class ProxyBytesResult:
    """HTTP-neutral upstream response returned by the Engine gateway service."""

    status: int
    payload: bytes
    content_type: str
