#!/usr/bin/env python3
"""Provide precompute-similar-ann runtime helpers."""

import argparse
import logging
import signal
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    import faiss  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is required. Install faiss-cpu in your Python environment."
    ) from exc

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter


SIMILARITY_ITEM_METADATA_COLUMNS = [
    ("similar_video_uuid", "TEXT"),
    ("similar_video_numeric_id", "INTEGER"),
    ("similar_channel_id", "TEXT"),
    ("similar_channel_name", "TEXT"),
    ("similar_channel_url", "TEXT"),
    ("similar_channel_avatar_url", "TEXT"),
    ("similar_account_name", "TEXT"),
    ("similar_account_url", "TEXT"),
    ("similar_title", "TEXT"),
    ("similar_description", "TEXT"),
    ("similar_tags_json", "TEXT"),
    ("similar_category", "TEXT"),
    ("similar_published_at", "INTEGER"),
    ("similar_video_url", "TEXT"),
    ("similar_duration", "REAL"),
    ("similar_thumbnail_url", "TEXT"),
    ("similar_embed_path", "TEXT"),
    ("similar_views", "INTEGER"),
    ("similar_likes", "INTEGER"),
    ("similar_dislikes", "INTEGER"),
    ("similar_comments_count", "INTEGER"),
    ("similar_nsfw", "INTEGER"),
    ("similar_preview_path", "TEXT"),
    ("similar_last_checked_at", "INTEGER"),
]

SIMILARITY_ITEM_METADATA_FIELDS = [
    "video_uuid",
    "video_numeric_id",
    "channel_id",
    "channel_name",
    "channel_url",
    "channel_avatar_url",
    "account_name",
    "account_url",
    "title",
    "description",
    "tags_json",
    "category",
    "published_at",
    "video_url",
    "duration",
    "thumbnail_url",
    "embed_path",
    "views",
    "likes",
    "dislikes",
    "comments_count",
    "nsfw",
    "preview_path",
    "last_checked_at",
]

SIMILARITY_ITEM_COLUMNS = [
    "source_video_id",
    "source_instance_domain",
    "similar_video_id",
    "similar_instance_domain",
    "score",
    "rank",
    "similar_video_uuid",
    "similar_video_numeric_id",
    "similar_channel_id",
    "similar_channel_name",
    "similar_channel_url",
    "similar_channel_avatar_url",
    "similar_account_name",
    "similar_account_url",
    "similar_title",
    "similar_description",
    "similar_tags_json",
    "similar_category",
    "similar_published_at",
    "similar_video_url",
    "similar_duration",
    "similar_thumbnail_url",
    "similar_embed_path",
    "similar_views",
    "similar_likes",
    "similar_dislikes",
    "similar_comments_count",
    "similar_nsfw",
    "similar_preview_path",
    "similar_last_checked_at",
]


def connect_db(path: Path) -> sqlite3.Connection:
    """Handle connect db."""
    conn = sqlite3.connect(path.as_posix())
    conn.row_factory = sqlite3.Row
    return conn


def connect_source_db(path: Path) -> sqlite3.Connection:
    """Handle connect source db."""
    quoted = path.as_posix()
    uri = f"file:{quoted}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def iter_embedding_rows_by_rowids(
    conn: sqlite3.Connection, rowids: list[int], batch_size: int = 512
):
    """Handle iter embedding rows by rowids."""
    if not rowids:
        return
    for start in range(0, len(rowids), batch_size):
        chunk = rowids[start : start + batch_size]
        placeholders = ",".join("?" for _ in chunk)
        query = f"""
            SELECT rowid, video_id, instance_domain, embedding, embedding_dim
            FROM video_embeddings
            WHERE rowid IN ({placeholders})
        """
        for row in conn.execute(query, chunk):
            yield row


def iter_row_batches(row_iter: Any, batch_size: int):
    """Yield source rows in fixed-size batches for vectorized ANN search."""
    if batch_size <= 0:
        batch_size = 1
    batch: list[Any] = []
    for row in row_iter:
        batch.append(row)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def build_query_batch(rows: list[Any], dim_value: int) -> tuple[list[Any], np.ndarray]:
    """Build a float32 query matrix from valid embedding rows."""
    valid_rows: list[Any] = []
    vectors: list[np.ndarray] = []
    for row in rows:
        if row["embedding_dim"] != dim_value:
            continue
        embedding = np.frombuffer(row["embedding"], dtype=np.float32)
        if embedding.shape[0] != dim_value:
            continue
        valid_rows.append(row)
        vectors.append(embedding)
    if not valid_rows:
        return [], np.empty((0, dim_value), dtype=np.float32)
    return valid_rows, np.vstack(vectors)


def set_nprobe(index: faiss.Index, nprobe: int) -> None:
    """Set FAISS nprobe on IVF-like indexes (CPU and GPU wrappers)."""
    ivf_index = None
    if hasattr(faiss, "extract_index_ivf"):
        try:
            ivf_index = faiss.extract_index_ivf(index)
        except Exception:  # pragma: no cover
            ivf_index = None
    if ivf_index is not None:
        ivf_index.nprobe = nprobe
    if hasattr(index, "nprobe"):
        index.nprobe = nprobe
    elif hasattr(index, "index") and hasattr(index.index, "nprobe"):
        index.index.nprobe = nprobe


def move_index_to_gpu(index: faiss.Index, device: int) -> tuple[faiss.Index, Any]:
    """Move a CPU FAISS index to GPU and keep resources alive."""
    if device < 0:
        raise RuntimeError("GPU mode requested with invalid --gpu-device (< 0).")
    if not hasattr(faiss, "StandardGpuResources") or not hasattr(faiss, "index_cpu_to_gpu"):
        raise RuntimeError(
            "GPU mode requested but installed FAISS has no GPU support. "
            "Install faiss-gpu (matching CUDA) or run without --gpu."
        )
    gpu_resources = faiss.StandardGpuResources()
    gpu_index = faiss.index_cpu_to_gpu(gpu_resources, device, index)
    return gpu_index, gpu_resources


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Handle ensure schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS similarity_sources (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          computed_at INTEGER NOT NULL,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS similarity_items (
          source_video_id TEXT NOT NULL,
          source_instance_domain TEXT NOT NULL,
          similar_video_id TEXT NOT NULL,
          similar_instance_domain TEXT NOT NULL,
          score REAL,
          rank INTEGER NOT NULL,
          similar_video_uuid TEXT,
          similar_video_numeric_id INTEGER,
          similar_channel_id TEXT,
          similar_channel_name TEXT,
          similar_channel_url TEXT,
          similar_channel_avatar_url TEXT,
          similar_account_name TEXT,
          similar_account_url TEXT,
          similar_title TEXT,
          similar_description TEXT,
          similar_tags_json TEXT,
          similar_category TEXT,
          similar_published_at INTEGER,
          similar_video_url TEXT,
          similar_duration REAL,
          similar_thumbnail_url TEXT,
          similar_embed_path TEXT,
          similar_views INTEGER,
          similar_likes INTEGER,
          similar_dislikes INTEGER,
          similar_comments_count INTEGER,
          similar_nsfw INTEGER,
          similar_preview_path TEXT,
          similar_last_checked_at INTEGER,
          PRIMARY KEY (
            source_video_id,
            source_instance_domain,
            similar_video_id,
            similar_instance_domain
          )
        );
        CREATE INDEX IF NOT EXISTS similarity_source_rank_idx
          ON similarity_items (source_video_id, source_instance_domain, rank);
        """
    )
    _ensure_similarity_item_columns(conn)


def _ensure_similarity_item_columns(conn: sqlite3.Connection) -> None:
    """Handle ensure similarity item columns."""
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(similarity_items)").fetchall()
    }
    for column, column_type in SIMILARITY_ITEM_METADATA_COLUMNS:
        if column in existing:
            continue
        conn.execute(f"ALTER TABLE similarity_items ADD COLUMN {column} {column_type}")


def fetch_metadata(conn: sqlite3.Connection, rowids: list[int]) -> dict[int, dict[str, Any]]:
    """Handle fetch metadata."""
    if not rowids:
        return {}
    placeholders = ", ".join("?" for _ in rowids)
    rows = conn.execute(
        f"""
        SELECT
          e.rowid AS rowid,
          v.video_id,
          v.video_uuid,
          v.video_numeric_id,
          v.instance_domain,
          v.channel_id,
          v.channel_name,
          v.channel_url,
          c.avatar_url AS channel_avatar_url,
          v.account_name,
          v.account_url,
          v.title,
          v.description,
          v.tags_json,
          v.category,
          v.published_at,
          v.video_url,
          v.duration,
          v.thumbnail_url,
          v.embed_path,
          v.views,
          v.likes,
          v.dislikes,
          v.comments_count,
          v.nsfw,
          v.preview_path,
          v.last_checked_at
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE e.rowid IN ({placeholders})
        """,
        rowids,
    ).fetchall()
    return {row["rowid"]: dict(row) for row in rows}


def fetch_metadata_chunked(
    conn: sqlite3.Connection,
    rowids: list[int],
    chunk_size: int = 5000,
) -> dict[int, dict[str, Any]]:
    """Fetch metadata for many rowids in chunks to stay under SQLite variable limits."""
    if not rowids:
        return {}
    if chunk_size <= 0:
        chunk_size = 5000
    merged: dict[int, dict[str, Any]] = {}
    for start in range(0, len(rowids), chunk_size):
        chunk = rowids[start : start + chunk_size]
        merged.update(fetch_metadata(conn, chunk))
    return merged


def _extract_similarity_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Handle extract similarity metadata."""
    return {field: meta.get(field) for field in SIMILARITY_ITEM_METADATA_FIELDS}


def record_similarities(
    conn: sqlite3.Connection,
    source: dict[str, Any],
    items: list[dict[str, Any]],
    computed_at: int,
) -> None:
    """Handle record similarities."""
    conn.execute(
        """
        INSERT INTO similarity_sources (video_id, instance_domain, computed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(video_id, instance_domain)
        DO UPDATE SET computed_at = excluded.computed_at
        """,
        (source["video_id"], source["instance_domain"], computed_at),
    )
    conn.execute(
        """
        DELETE FROM similarity_items
        WHERE source_video_id = ? AND source_instance_domain = ?
        """,
        (source["video_id"], source["instance_domain"]),
    )
    values = [
        (
            source["video_id"],
            source["instance_domain"],
            item["video_id"],
            item["instance_domain"],
            item["score"],
            item["rank"],
            item.get("video_uuid"),
            item.get("video_numeric_id"),
            item.get("channel_id"),
            item.get("channel_name"),
            item.get("channel_url"),
            item.get("channel_avatar_url"),
            item.get("account_name"),
            item.get("account_url"),
            item.get("title"),
            item.get("description"),
            item.get("tags_json"),
            item.get("category"),
            item.get("published_at"),
            item.get("video_url"),
            item.get("duration"),
            item.get("thumbnail_url"),
            item.get("embed_path"),
            item.get("views"),
            item.get("likes"),
            item.get("dislikes"),
            item.get("comments_count"),
            item.get("nsfw"),
            item.get("preview_path"),
            item.get("last_checked_at"),
        )
        for item in items
    ]
    placeholders = ", ".join(["?"] * len(SIMILARITY_ITEM_COLUMNS))
    conn.executemany(
        f"""
        INSERT INTO similarity_items (
          {", ".join(SIMILARITY_ITEM_COLUMNS)}
        )
        VALUES ({placeholders})
        """,
        values,
    )


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(
        description="Precompute similar videos with FAISS.",
        formatter_class=CompactHelpFormatter,
    )
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    default_index = script_dir.parent / "whitelist-video-embeddings.faiss"
    default_out = script_dir.parent / "similarity-cache.db"
    parser.add_argument("--db", default=str(default_db), help="Path to crawl database.")
    parser.add_argument("--index", default=str(default_index), help="Path to FAISS index.")
    parser.add_argument("--out", default=str(default_out), help="Output cache database.")
    parser.add_argument("--top-k", type=int, default=20, help="Similar items to keep.")
    parser.add_argument("--nprobe", type=int, default=16, help="FAISS nprobe setting.")
    parser.add_argument(
        "--search-batch-size",
        type=int,
        default=256,
        help="ANN query batch size (number of source videos per FAISS search call).",
    )
    accel_group = parser.add_mutually_exclusive_group(required=True)
    accel_group.add_argument(
        "--cpu",
        action="store_true",
        help="Use FAISS CPU search acceleration.",
    )
    accel_group.add_argument(
        "--gpu",
        action="store_true",
        help="Use FAISS GPU search acceleration.",
    )
    parser.add_argument(
        "--gpu-device",
        type=int,
        default=None,
        help="CUDA device id used when --gpu is enabled (default: 0).",
    )
    parser.add_argument("--reset", action="store_true", help="Clear existing cache.")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Compute only for videos that do not exist in similarity_sources.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    stop_requested = False
    stop_reason = "completed"

    def _signal_name(signum: int) -> str:
        """Return a stable signal name for lifecycle logs."""
        try:
            return signal.Signals(signum).name
        except ValueError:
            return str(signum)

    def _request_soft_stop(signum: int, _frame: Any) -> None:
        """Request graceful shutdown and let the current batch finish."""
        nonlocal stop_requested, stop_reason
        if stop_requested:
            return
        stop_requested = True
        stop_reason = f"signal:{_signal_name(signum)}"
        logging.warning(
            "soft-stop requested by %s; finishing current batch and committing",
            _signal_name(signum),
        )

    managed_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGTSTP"):
        managed_signals.append(signal.SIGTSTP)
    previous_handlers = {sig: signal.getsignal(sig) for sig in managed_signals}
    for sig in managed_signals:
        signal.signal(sig, _request_soft_stop)

    try:
        src_db = connect_source_db(Path(args.db))
        out_db = connect_db(Path(args.out))
        ensure_schema(out_db)
        if args.reset:
            out_db.executescript("DELETE FROM similarity_items; DELETE FROM similarity_sources;")

        dim_row = src_db.execute("SELECT embedding_dim FROM video_embeddings LIMIT 1").fetchone()
        if not dim_row:
            raise RuntimeError("No embeddings found in database.")
        dim_value = int(dim_row[0])

        index = faiss.read_index(str(args.index), faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
        # Keep a reference so FAISS GPU resources live for the full run.
        gpu_resources = None
        if args.cpu:
            logging.info("faiss acceleration=cpu")
            if args.gpu_device is not None:
                raise RuntimeError("--gpu-device can be used only together with --gpu.")
        else:
            gpu_device = 0 if args.gpu_device is None else args.gpu_device
            index, gpu_resources = move_index_to_gpu(index, gpu_device)
            logging.info("faiss acceleration=gpu device=%d", gpu_device)
        set_nprobe(index, args.nprobe)
        if index.d != dim_value:
            raise RuntimeError(
                f"Index dimension {index.d} does not match database dimension {dim_value}"
            )

        if args.incremental:
            # Incremental mode compares source embeddings with already-computed rows
            # from the output cache DB. We materialize only rowids first to avoid
            # lock contention while writing to the output DB.
            out_uri = f"file:{Path(args.out).as_posix()}?mode=ro"
            src_db.execute("ATTACH DATABASE ? AS out_cache", (out_uri,))
            pending_rowids = [
                int(row["rowid"])
                for row in src_db.execute(
                    """
                    SELECT e.rowid
                    FROM video_embeddings e
                    LEFT JOIN out_cache.similarity_sources s
                      ON s.video_id = e.video_id
                     AND s.instance_domain = e.instance_domain
                    WHERE s.video_id IS NULL
                    """
                )
            ]
            src_db.execute("DETACH DATABASE out_cache")
            row_iter = iter_embedding_rows_by_rowids(src_db, pending_rowids)
        else:
            row_iter = src_db.execute(
                """
                SELECT rowid, video_id, instance_domain, embedding, embedding_dim
                FROM video_embeddings
                """
            )
        computed_at = int(datetime.now(timezone.utc).timestamp() * 1000)
        processed = 0
        if args.search_batch_size <= 0:
            raise RuntimeError("--search-batch-size must be > 0")
        try:
            for source_batch in iter_row_batches(row_iter, args.search_batch_size):
                valid_rows, query_batch = build_query_batch(source_batch, dim_value)
                if not valid_rows:
                    if stop_requested:
                        break
                    continue

                scores_batch, ids_batch = index.search(query_batch, args.top_k + 1)
                batch_rowids = sorted(
                    {
                        int(rowid)
                        for ids_row in ids_batch
                        for rowid in ids_row
                        if int(rowid) > 0
                    }
                )
                metadata_by_rowid = fetch_metadata_chunked(src_db, batch_rowids)

                for row, scores_row, ids_row in zip(valid_rows, scores_batch, ids_batch):
                    items: list[dict[str, Any]] = []
                    for score, rowid in zip(scores_row, ids_row):
                        rowid_int = int(rowid)
                        if rowid_int == row["rowid"] or rowid_int <= 0:
                            continue
                        meta = metadata_by_rowid.get(rowid_int)
                        if not meta:
                            continue
                        items.append(
                            {
                                "video_id": meta["video_id"],
                                "instance_domain": meta["instance_domain"],
                                "score": float(score),
                                **_extract_similarity_metadata(meta),
                            }
                        )
                        if len(items) >= args.top_k:
                            break
                    record_similarities(
                        out_db,
                        {"video_id": row["video_id"], "instance_domain": row["instance_domain"]},
                        [
                            {**item, "rank": rank}
                            for rank, item in enumerate(items, start=1)
                        ],
                        computed_at,
                    )
                    processed += 1
                    if processed % 500 == 0:
                        out_db.commit()
                        logging.info("processed %d videos", processed)
                    if stop_requested:
                        break
                if stop_requested:
                    break
        except KeyboardInterrupt:
            stop_requested = True
            stop_reason = "keyboard_interrupt"
            logging.warning("soft-stop requested by KeyboardInterrupt; committing")

        out_db.commit()
        if stop_requested:
            logging.info("soft-stop complete reason=%s processed=%d", stop_reason, processed)
        else:
            logging.info("done. processed=%d", processed)
        _ = gpu_resources
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
