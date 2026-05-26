"""Compatibility exports for historical Engine recommendation helper imports.

Active Engine HTTP routing now lives in ``engine/server/api/app.py`` and
``engine/server/api/routes/*``. This module intentionally keeps only helper
re-exports used by older tests/import paths; it no longer owns route dispatch or
stdlib HTTP handler classes.
"""
from __future__ import annotations

try:
    from engine.server.api.services.recommendation_service import (
        _extract_video_id_from_similar_path,
        _parse_bool,
        _parse_client_likes,
        _parse_int,
        _parse_non_negative_int,
        _recommendations_likes_payload_error,
        _resolve_client_likes,
        maybe_attach_debug,
        stable_video_row,
        stable_video_rows,
    )
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.recommendation_service import (
        _extract_video_id_from_similar_path,
        _parse_bool,
        _parse_client_likes,
        _parse_int,
        _parse_non_negative_int,
        _recommendations_likes_payload_error,
        _resolve_client_likes,
        maybe_attach_debug,
        stable_video_row,
        stable_video_rows,
    )


SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}

__all__ = [
    "SIMILAR_POST_ROUTES",
    "_extract_video_id_from_similar_path",
    "_parse_bool",
    "_parse_client_likes",
    "_parse_int",
    "_parse_non_negative_int",
    "_recommendations_likes_payload_error",
    "_resolve_client_likes",
    "maybe_attach_debug",
    "stable_video_row",
    "stable_video_rows",
]
