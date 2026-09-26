#!/usr/bin/env python3
"""Client backend executable entrypoint for the FastAPI app."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from app import create_app
from lib.http_utils import RateLimiter
from repositories.users import UsersRepository
from runtime import ClientRuntimeState
from services.bridge_publisher import resolve_publish_mode

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent

DEFAULT_CLIENT_HOST = "127.0.0.1"
DEFAULT_CLIENT_PORT = 7172
DEFAULT_ENGINE_INGEST_BASE = "http://127.0.0.1:7070"
DEFAULT_USERS_DB_PATH = "client/backend/db/users.db"
DEFAULT_CLIENT_PUBLISH_MODE = os.environ.get("CLIENT_PUBLISH_MODE", "bridge").strip().lower()
RATE_LIMIT_MAX_REQUESTS = 90
RATE_LIMIT_WINDOW_SECONDS = 60


def _emit_client_log(
    level: int,
    event: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Emit one structured JSON log line for Client backend service."""
    payload: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level),
        "service": "client-backend",
        "event": event,
        "message": message,
    }
    if context:
        payload["context"] = context
    logging.log(level, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def parse_args() -> argparse.Namespace:
    """Parse Client backend command-line options."""
    parser = argparse.ArgumentParser(description="Run PeerTube Client backend service.")
    parser.add_argument("--host", default=DEFAULT_CLIENT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_CLIENT_PORT)
    parser.add_argument(
        "--engine-url", dest="engine_ingest_base", default=DEFAULT_ENGINE_INGEST_BASE
    )
    parser.add_argument("--publish-mode", default=resolve_publish_mode(DEFAULT_CLIENT_PUBLISH_MODE))
    return parser.parse_args()


def connect_db(path: Path) -> sqlite3.Connection:
    """Open the Client users SQLite database with current row semantics."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    """Run the Client backend FastAPI service through the compatibility entrypoint."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_id = str(uuid4())

    users_db_path = (ROOT_DIR / DEFAULT_USERS_DB_PATH).resolve()
    users_db_path.parent.mkdir(parents=True, exist_ok=True)
    user_db = connect_db(users_db_path)
    users = UsersRepository(user_db)
    users.ensure_schema()
    state = ClientRuntimeState.create(
        user_db,
        args.engine_ingest_base,
        args.publish_mode,
        RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS),
    )
    app = create_app(state)
    _emit_client_log(
        logging.INFO,
        "service.start",
        "client backend listening",
        {
            "host": args.host,
            "port": int(args.port),
            "engine_ingest_base": args.engine_ingest_base,
            "publish_mode": resolve_publish_mode(args.publish_mode),
            "run_id": run_id,
            "pid": os.getpid(),
            "framework": "fastapi",
        },
    )
    try:
        uvicorn.run(app, host=args.host, port=int(args.port), log_level="info", access_log=False)
    finally:
        _emit_client_log(
            logging.INFO,
            "service.stop",
            "client backend shutting down",
            {"reason": "uvicorn_exit", "run_id": run_id, "pid": os.getpid()},
        )
        user_db.close()


if __name__ == "__main__":
    main()
