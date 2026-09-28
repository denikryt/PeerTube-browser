#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TMP_DIR="$(mktemp -d /tmp/plan18-rollout-smoke.XXXXXX)"
DB_PATH="${TMP_DIR}/whitelist.db"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

resolve_python() {
  if [[ -x "${ROOT_DIR}/venv/bin/python3" ]]; then
    printf '%s\n' "${ROOT_DIR}/venv/bin/python3"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  echo "[plan18-rollout-smoke] ERROR: python3 not found" >&2
  exit 1
}

PYTHON_BIN="$(resolve_python)"

# Build the pre-plan-18 state deliberately without video_tags, facet snapshot,
# or the new Fresh/Trending indexes. The rollout commands below must make this
# database ready before any Engine request surface is constructed.
"${PYTHON_BIN}" - "${DB_PATH}" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
conn = sqlite3.connect(path)
conn.executescript(
    """
    CREATE TABLE channels (
      channel_id TEXT NOT NULL,
      instance_domain TEXT NOT NULL,
      followers_count INTEGER,
      videos_count INTEGER,
      channel_name TEXT,
      display_name TEXT,
      avatar_url TEXT,
      PRIMARY KEY(channel_id, instance_domain)
    );
    CREATE TABLE videos (
      video_id TEXT NOT NULL,
      video_uuid TEXT,
      video_numeric_id INTEGER,
      instance_domain TEXT NOT NULL,
      channel_id TEXT,
      channel_name TEXT,
      channel_url TEXT,
      account_name TEXT,
      account_url TEXT,
      title TEXT,
      description TEXT,
      tags_json TEXT,
      category TEXT,
      category_id TEXT,
      language TEXT,
      language_label TEXT,
      published_at INTEGER,
      video_url TEXT,
      duration INTEGER,
      thumbnail_url TEXT,
      embed_path TEXT,
      views INTEGER,
      likes INTEGER,
      dislikes INTEGER,
      comments_count INTEGER,
      nsfw INTEGER,
      preview_path TEXT,
      popularity REAL,
      last_checked_at INTEGER,
      error_count INTEGER NOT NULL DEFAULT 0,
      invalid_reason TEXT,
      PRIMARY KEY(video_id, instance_domain)
    );
    CREATE TABLE video_embeddings (
      video_id TEXT NOT NULL,
      instance_domain TEXT NOT NULL,
      PRIMARY KEY(video_id, instance_domain)
    );
    CREATE TABLE instance_denylist (
      host TEXT PRIMARY KEY,
      is_active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE channel_moderation (
      channel_id TEXT NOT NULL,
      instance_domain TEXT NOT NULL,
      status TEXT NOT NULL,
      PRIMARY KEY(channel_id, instance_domain)
    );
    CREATE INDEX idx_videos_popularity ON videos(popularity DESC);
    """
)
conn.execute(
    "INSERT INTO channels VALUES (?, ?, ?, ?, ?, ?, ?)",
    ("channel-1", "example.org", 10, 1, "channel", "Channel", "/avatar.png"),
)
conn.execute(
    """
    INSERT INTO videos(
      video_id, video_uuid, video_numeric_id, instance_domain, channel_id,
      channel_name, channel_url, account_name, account_url, title, description,
      tags_json, category, category_id, language, language_label, published_at,
      video_url, duration, thumbnail_url, embed_path, views, likes, dislikes,
      comments_count, nsfw, preview_path, popularity, last_checked_at,
      error_count, invalid_reason
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    (
        "linux-video", "uuid-linux-video", 1, "example.org", "channel-1",
        "channel", "https://example.org/c/channel", "account",
        "https://example.org/a/account", "Linux video", "description",
        '[" Linux ", "linux"]', "Education", "13", "en", "English",
        1700000000, "https://example.org/w/linux-video", 120, "/thumb.jpg",
        "/embed", 100, 10, 0, 1, 0, "/preview.jpg", 42.0, 1700000100,
        0, None,
    ),
)
conn.commit()
conn.close()
PY

# Negative side of the rollout invariant: the legacy DB is not ready for the
# new tag/facet runtime contract before the explicit bootstrap runs.
"${PYTHON_BIN}" - "${ROOT_DIR}" "${DB_PATH}" <<'PY'
import sqlite3
import sys
from pathlib import Path

root = Path(sys.argv[1])
db_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "engine" / "server"))
from data.prepared_discovery import prepared_discovery_available

conn = sqlite3.connect(db_path)
if prepared_discovery_available(conn):
    raise SystemExit("legacy DB unexpectedly reports prepared Discovery ready")
if conn.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_tags'"
).fetchone() is not None:
    raise SystemExit("legacy DB unexpectedly contains video_tags")
conn.close()
PY

"${PYTHON_BIN}" "${ROOT_DIR}/engine/server/db/jobs/ensure-video-indexes.py" --db "${DB_PATH}"
"${PYTHON_BIN}" "${ROOT_DIR}/engine/server/db/jobs/rebuild-video-discovery-data.py" --db "${DB_PATH}"

# Only after the durable prepared check succeeds do we construct the Engine app
# and exercise the two runtime reads that depend on the rollout artifacts.
"${PYTHON_BIN}" - "${ROOT_DIR}" "${DB_PATH}" <<'PY'
from __future__ import annotations

import sqlite3
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

root = Path(sys.argv[1])
db_path = Path(sys.argv[2])
server_dir = root / "engine" / "server"
api_dir = server_dir / "api"
sys.path.insert(0, str(api_dir))
sys.path.insert(0, str(server_dir))

# The smoke does not exercise ANN, so keep that optional dependency outside the
# rollout contract while importing the complete FastAPI application factory.
fake_ann = types.ModuleType("data.ann")
fake_ann.search_index = lambda *_args, **_kwargs: ([], [])
sys.modules.setdefault("data.ann", fake_ann)

from fastapi.testclient import TestClient
from app import create_app
from data.prepared_discovery import prepared_discovery_available

conn = sqlite3.connect(db_path, check_same_thread=False)
conn.row_factory = sqlite3.Row

if not prepared_discovery_available(conn):
    raise SystemExit("prepared Discovery is not ready; Engine request surface must not start")

indexes = {
    row[1]
    for row in conn.execute("PRAGMA index_list('videos')")
}
required = {"idx_videos_fresh_order", "idx_videos_trending_order"}
if not required.issubset(indexes):
    raise SystemExit(f"missing rollout indexes: {sorted(required - indexes)}")
if "idx_videos_popularity" in indexes:
    raise SystemExit("legacy idx_videos_popularity survived rollout")

state = SimpleNamespace(
    db=conn,
    db_lock=threading.RLock(),
    rate_limiter=None,
    video_error_threshold=3,
    enable_instance_ignore=True,
    enable_channel_blocklist=True,
)
with TestClient(create_app(state)) as client:
    discovery = client.get("/internal/discovery/fresh?tag=linux&limit=5")
    if discovery.status_code != 200:
        raise SystemExit(f"tag discovery failed: {discovery.status_code} {discovery.text}")
    ids = [row["video_id"] for row in discovery.json()["rows"]]
    if ids != ["linux-video"]:
        raise SystemExit(f"unexpected tag discovery rows: {ids}")

    facets = client.get("/internal/video-facets")
    if facets.status_code != 200:
        raise SystemExit(f"facets failed: {facets.status_code} {facets.text}")
    tag_counts = {row["value"]: row["count"] for row in facets.json()["tags"]}
    if tag_counts.get("linux") != 1:
        raise SystemExit(f"unexpected facet tags: {tag_counts}")

conn.close()
print("[plan18-rollout-smoke] PASS")
PY
