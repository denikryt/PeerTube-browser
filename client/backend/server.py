#!/usr/bin/env python3
"""Client backend service for write/profile endpoints and bridge publishing."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent
ENGINE_SERVER_DIR = ROOT_DIR / "engine" / "server"
ENGINE_API_DIR = ENGINE_SERVER_DIR / "api"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ENGINE_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_SERVER_DIR))
if str(ENGINE_API_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_API_DIR))

from engine.server.api.http_utils import (  # type: ignore
    RateLimiter,
    read_json_body,
    respond_json,
    respond_options,
    resolve_user_id,
)
from engine.server.data.embeddings import fetch_seed_embedding  # type: ignore
from engine.server.data.metadata import fetch_metadata_by_ids  # type: ignore
from engine.server.data.time import now_ms  # type: ignore
from engine.server.data.users import (  # type: ignore
    clear_likes,
    ensure_user_schema,
    fetch_recent_likes,
    get_or_create_user,
    record_like,
)
from engine.server.api.recommendations.keys import like_key  # type: ignore


DEFAULT_CLIENT_HOST = "127.0.0.1"
DEFAULT_CLIENT_PORT = 7172
DEFAULT_ENGINE_INGEST_BASE = "http://127.0.0.1:7171"
DEFAULT_ENGINE_DB_PATH = "engine/server/db/whitelist.db"
DEFAULT_USERS_DB_PATH = "client/backend/db/users.db"
DEFAULT_CLIENT_PUBLISH_MODE = os.environ.get("CLIENT_PUBLISH_MODE", "bridge").strip().lower()
MAX_LIKES = 100
MAX_CLIENT_LIKES = 200
RATE_LIMIT_MAX_REQUESTS = 90
RATE_LIMIT_WINDOW_SECONDS = 60


def _resolve_mode(value: str, default: str = "bridge") -> str:
    normalized = value.strip().lower()
    return normalized if normalized in {"bridge", "activitypub"} else default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PeerTube Client backend service.")
    parser.add_argument("--host", default=DEFAULT_CLIENT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_CLIENT_PORT)
    parser.add_argument("--engine-db", default=DEFAULT_ENGINE_DB_PATH)
    parser.add_argument("--users-db", default=DEFAULT_USERS_DB_PATH)
    parser.add_argument("--engine-ingest-base", default=DEFAULT_ENGINE_INGEST_BASE)
    parser.add_argument("--publish-mode", default=_resolve_mode(DEFAULT_CLIENT_PUBLISH_MODE))
    return parser.parse_args()


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class ClientBackendServer(ThreadingHTTPServer):
    """Threaded server with shared DB handles and config."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        engine_db: sqlite3.Connection,
        user_db: sqlite3.Connection,
        engine_ingest_base: str,
        publish_mode: str,
        rate_limiter: RateLimiter,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.engine_db = engine_db
        self.user_db = user_db
        self.engine_ingest_base = engine_ingest_base.rstrip("/")
        self.publish_mode = _resolve_mode(publish_mode)
        self.rate_limiter = rate_limiter


class ClientBackendHandler(BaseHTTPRequestHandler):
    """HTTP handler for Client backend write/profile endpoints."""

    def do_OPTIONS(self) -> None:  # noqa: N802
        respond_options(self)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if url.path == "/api/health":
            respond_json(
                self,
                200,
                {
                    "ok": True,
                    "service": "client-backend",
                    "engine_ingest_base": self.server.engine_ingest_base,
                    "publish_mode": self.server.publish_mode,
                },
            )
            return
        if url.path == "/api/user-profile":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
            with self.server.user_db:
                get_or_create_user(self.server.user_db, user_id)
                likes = fetch_recent_likes(self.server.user_db, user_id, MAX_LIKES)
            respond_json(self, 200, {"user_id": user_id, "likes": likes, "updatedAt": now_ms()})
            return
        if url.path == "/api/user-profile/likes":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_likes_get(params)
            return
        respond_json(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/api/user-action":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_action()
            return
        if url.path == "/api/user-profile/reset":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_reset()
            return
        if url.path == "/api/user-profile/likes":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_likes_from_client()
            return
        if url.path == "/client/events/publish":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_client_publish_event()
            return
        respond_json(self, 404, {"error": "Not found"})

    def _rate_limit_check(self, path: str) -> bool:
        ip = self.client_address[0] if self.client_address else "unknown"
        key = f"{ip}:{path}"
        return self.server.rate_limiter.allow(key)

    def _handle_user_action(self) -> None:
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        action = str(body.get("action") or "").strip().lower()
        if action not in {"like", "dislike", "undo_like"}:
            respond_json(self, 400, {"error": "Unsupported action"})
            return
        video_id = body.get("video_id")
        host = body.get("host")
        uuid = body.get("uuid")
        user_id_raw = body.get("user_id")
        if not video_id and not uuid:
            respond_json(self, 400, {"error": "Missing video_id or uuid"})
            return
        user_id = resolve_user_id(str(user_id_raw) if user_id_raw is not None else None)
        seed = fetch_seed_embedding(
            self.server.engine_db,
            str(video_id) if video_id is not None else None,
            str(host) if host is not None else None,
            str(uuid) if uuid is not None else None,
        )
        if not seed:
            respond_json(self, 404, {"error": "Video embedding not found"})
            return
        if action == "like":
            with self.server.user_db:
                record_like(self.server.user_db, user_id, "like", seed, MAX_LIKES)
            event_type = "Like"
        else:
            with self.server.user_db:
                _remove_like(
                    self.server.user_db,
                    user_id,
                    str(seed.get("video_id") or ""),
                    str(seed.get("instance_domain") or ""),
                )
            event_type = "UndoLike"

        event_payload = {
            "event_id": f"client-{uuid4()}",
            "event_type": event_type,
            "actor_id": user_id,
            "object": {
                "video_uuid": seed.get("video_uuid") or "",
                "instance_domain": seed.get("instance_domain") or "",
                "canonical_url": None,
            },
            "published_at": now_ms(),
            "source_instance": seed.get("instance_domain") or "",
            "raw_payload": body,
        }
        bridge_result = _publish_event(
            self.server.publish_mode,
            self.server.engine_ingest_base,
            event_payload,
        )
        status = 200 if bridge_result.get("ok") else 502
        respond_json(
            self,
            status,
            {
                "ok": bridge_result.get("ok", False),
                "bridge_ok": bridge_result.get("ok", False),
                "bridge_error": bridge_result.get("error"),
                "user_id": user_id,
                "updatedAt": now_ms(),
            },
        )

    def _handle_user_profile_reset(self) -> None:
        body = read_json_body(self)
        user_id_raw = body.get("user_id") if isinstance(body, dict) else None
        user_id = resolve_user_id(str(user_id_raw) if user_id_raw is not None else None)
        with self.server.user_db:
            get_or_create_user(self.server.user_db, user_id)
            clear_likes(self.server.user_db, user_id)
        respond_json(
            self,
            200,
            {"user_id": user_id, "likes": [], "updatedAt": now_ms()},
        )

    def _handle_user_profile_likes_get(self, params: dict[str, list[str]]) -> None:
        user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
        limit = _parse_int(params.get("limit", [None])[0])
        limit = min(limit, MAX_LIKES) if limit > 0 else MAX_LIKES
        with self.server.user_db:
            get_or_create_user(self.server.user_db, user_id)
            likes = fetch_recent_likes(self.server.user_db, user_id, limit)
        rows = _resolve_likes_to_metadata(self.server.engine_db, likes)
        respond_json(self, 200, {"user_id": user_id, "likes": rows, "updatedAt": now_ms()})

    def _handle_user_profile_likes_from_client(self) -> None:
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)
        if not likes:
            respond_json(self, 200, {"likes": [], "updatedAt": now_ms()})
            return
        resolved = _resolve_client_likes(self.server.engine_db, likes)
        rows = _resolve_likes_to_metadata(self.server.engine_db, resolved)
        respond_json(self, 200, {"likes": rows, "updatedAt": now_ms()})

    def _handle_client_publish_event(self) -> None:
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        if not isinstance(body, dict):
            respond_json(self, 400, {"error": "Invalid JSON body"})
            return
        if not body.get("event_id"):
            body["event_id"] = f"client-{uuid4()}"
        if not body.get("published_at"):
            body["published_at"] = now_ms()
        result = _publish_event(self.server.publish_mode, self.server.engine_ingest_base, body)
        status = 200 if result.get("ok") else 502
        respond_json(self, status, result)


def _publish_to_engine_bridge(engine_ingest_base: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{engine_ingest_base}/internal/events/ingest",
        data=data,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(request, timeout=6) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return {"ok": bool(parsed.get("ok", True)), "response": parsed}
    except HTTPError as exc:
        return {"ok": False, "error": f"engine bridge HTTP {exc.code}"}
    except (URLError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def _publish_event(
    publish_mode: str, engine_ingest_base: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if _resolve_mode(publish_mode) != "bridge":
        return {
            "ok": False,
            "error": "CLIENT_PUBLISH_MODE=activitypub is not implemented yet",
            "mode": _resolve_mode(publish_mode),
        }
    return _publish_to_engine_bridge(engine_ingest_base, payload)


def _remove_like(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> None:
    conn.execute(
        "DELETE FROM likes WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
        (user_id, video_id, instance_domain),
    )
    conn.commit()


def _parse_int(value: str | None) -> int:
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _parse_client_likes(payload: dict[str, Any], max_items: int) -> list[dict[str, str]]:
    raw = payload.get("likes")
    if not isinstance(raw, list):
        return []
    likes: list[dict[str, str]] = []
    for entry in raw[: max_items if max_items > 0 else None]:
        if not isinstance(entry, dict):
            continue
        uuid = entry.get("uuid")
        host = entry.get("host")
        if not isinstance(uuid, str) or not uuid.strip():
            continue
        if not isinstance(host, str) or not host.strip():
            continue
        likes.append({"video_uuid": uuid.strip(), "instance_domain": host.strip()})
    return likes


def _resolve_client_likes(
    engine_db: sqlite3.Connection, likes: list[dict[str, str]]
) -> list[dict[str, Any]]:
    if not likes:
        return []
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in likes:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    conditions = " OR ".join(["(video_uuid = ? AND instance_domain = ?)"] * len(unique))
    params: list[Any] = []
    for entry in unique:
        params.append(entry["video_uuid"])
        params.append(entry["instance_domain"])
    rows = engine_db.execute(
        f"""
        SELECT video_id, video_uuid, instance_domain
        FROM videos
        WHERE {conditions}
        """,
        params,
    ).fetchall()
    lookup = {
        f"{row['video_uuid']}::{row['instance_domain']}": row["video_id"] for row in rows
    }
    resolved: list[dict[str, Any]] = []
    for entry in unique:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        video_id = lookup.get(key)
        if not video_id:
            continue
        resolved.append(
            {
                "video_id": str(video_id),
                "video_uuid": entry["video_uuid"],
                "instance_domain": entry["instance_domain"],
            }
        )
    return resolved


def _resolve_likes_to_metadata(
    engine_db: sqlite3.Connection, likes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not likes:
        return []
    metadata = fetch_metadata_by_ids(engine_db, likes)
    rows: list[dict[str, Any]] = []
    for like in likes:
        meta = metadata.get(like_key(like))
        if meta:
            rows.append(meta)
    return rows


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    engine_db_path = (ROOT_DIR / args.engine_db).resolve()
    users_db_path = (ROOT_DIR / args.users_db).resolve()
    users_db_path.parent.mkdir(parents=True, exist_ok=True)
    engine_db = connect_db(engine_db_path)
    user_db = connect_db(users_db_path)
    ensure_user_schema(user_db)
    server = ClientBackendServer(
        (args.host, int(args.port)),
        ClientBackendHandler,
        engine_db,
        user_db,
        args.engine_ingest_base,
        args.publish_mode,
        RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS),
    )
    logging.info(
        "[client-backend] listening on http://%s:%s engine_ingest=%s publish_mode=%s",
        args.host,
        args.port,
        args.engine_ingest_base,
        _resolve_mode(args.publish_mode),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("shutting down")
    finally:
        server.server_close()
        engine_db.close()
        user_db.close()


if __name__ == "__main__":
    main()
