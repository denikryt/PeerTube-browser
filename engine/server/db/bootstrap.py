"""Bootstrap Engine-owned SQLite schemas before runtime and job use.

The functions in this module group the current-shape migration resources by
runtime ownership area. Legacy `ensure_*` wrappers remain available for one
compatibility stage, but production callers should use these explicit bootstrap
entrypoints.
"""
from __future__ import annotations

import sqlite3

try:
    from engine.server.db.migrations.apply import (
        apply_main_read_indexes,
        apply_main_runtime_migrations,
        apply_moderation_migration,
        apply_random_cache_migrations,
        apply_similarity_cache_migrations,
    )
except ModuleNotFoundError:  # pragma: no cover - script import fallback.
    from db.migrations.apply import (
        apply_main_read_indexes,
        apply_main_runtime_migrations,
        apply_moderation_migration,
        apply_random_cache_migrations,
        apply_similarity_cache_migrations,
    )


def bootstrap_engine_runtime_db(conn: sqlite3.Connection) -> None:
    """Apply Engine runtime tables and conditional read indexes."""
    apply_main_runtime_migrations(conn)


def bootstrap_engine_similarity_cache_db(conn: sqlite3.Connection) -> None:
    """Apply the current similarity-cache schema."""
    apply_similarity_cache_migrations(conn)


def bootstrap_engine_random_cache_db(conn: sqlite3.Connection) -> None:
    """Apply the current random-cache schema."""
    apply_random_cache_migrations(conn)


def bootstrap_engine_moderation_db(conn: sqlite3.Connection) -> None:
    """Apply only moderation schema for jobs that need moderation tables."""
    apply_moderation_migration(conn)


def bootstrap_engine_read_indexes(conn: sqlite3.Connection) -> None:
    """Apply conditional Engine read indexes for existing content tables."""
    apply_main_read_indexes(conn)
