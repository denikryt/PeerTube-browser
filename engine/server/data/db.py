"""Provide db runtime helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_db(path: Path) -> sqlite3.Connection:
    """Open the crawl database for shared reads and writes."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def connect_user_db(path: Path) -> sqlite3.Connection:
    """Open or create the users database."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def connect_similarity_db(path: Path) -> sqlite3.Connection:
    """Open the similarity cache database."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
