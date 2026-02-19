#!/usr/bin/env python3
"""Build or update embeddings for videos stored in a SQLite database."""
import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter


def parse_tags(tags_json: str | None) -> list[str]:
    """Handle parse tags."""
    if not tags_json:
        return []
    try:
        value = json.loads(tags_json)
    except json.JSONDecodeError:
        return [tags_json.strip()] if tags_json.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()] if str(value).strip() else []


def build_text(row: sqlite3.Row) -> str | None:
    """Handle build text."""
    parts: list[str] = []
    title = (row["title"] or "").strip()
    description = (row["description"] or "").strip()
    category = (row["category"] or "").strip()
    channel_name = (row["channel_name"] or "").strip()
    comments_count = row["comments_count"]

    if title:
        parts.append(title)
    if description:
        parts.append(description)

    tags = parse_tags(row["tags_json"])
    if tags:
        parts.append("tags: " + ", ".join(tags))
    if category:
        parts.append(f"category: {category}")
    if channel_name:
        parts.append(f"channel: {channel_name}")
    if comments_count is not None:
        parts.append(f"comments_count: {comments_count}")

    text = "\n".join(parts).strip()
    return text if text else None


def init_schema(conn: sqlite3.Connection) -> None:
    """Handle init schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL,
          model_name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (video_id, instance_domain),
          FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
        );
        """
    )
    conn.commit()


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(
        description=(
            "Build sentence embeddings for videos and store them in video_embeddings. "
            "The script reads videos from the selected database, builds a text payload "
            "from title/description/tags/category/channel/comments, and stores a "
            "normalized embedding vector per (video_id, instance_domain)."
        ),
        formatter_class=CompactHelpFormatter,
    )
    repo_root = Path(__file__).resolve().parents[4]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    parser.add_argument(
        "--db-path",
        default=str(default_db),
        help=(
            "Path to sqlite database that contains videos and video_embeddings."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help=(
            "Batch size for embedding generation. Larger is faster but uses more RAM."
        ),
    )
    parser.add_argument(
        "--model-name",
        default="all-MiniLM-L6-v2",
        help=(
            "SentenceTransformer model name to load."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Recompute and overwrite all embeddings.\n"
            "Without --force, only videos missing embeddings are processed."
        ),
    )
    accel_group = parser.add_mutually_exclusive_group(required=True)
    accel_group.add_argument(
        "--cpu",
        dest="use_gpu",
        action="store_false",
        help="Run embedding generation on CPU.",
    )
    accel_group.add_argument(
        "--gpu",
        dest="use_gpu",
        action="store_true",
        help="Run embedding generation on GPU (CUDA).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)

    device = "cuda" if args.use_gpu else "cpu"
    if args.use_gpu and not torch.cuda.is_available():
        raise RuntimeError("GPU requested but CUDA is not available.")
    logging.info("loading model name=%s device=%s", args.model_name, device)
    model = SentenceTransformer(args.model_name, device=device)
    logging.info("model loaded")

    total_videos = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    existing_embeddings = conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone()[0]
    logging.info(
        "totals videos=%d embeddings_existing=%d", total_videos, existing_embeddings
    )

    if args.force:
        logging.info("force enabled: deleting existing embeddings")
        conn.execute("DELETE FROM video_embeddings")
        conn.commit()
        logging.info("scanning all videos")
        cursor = conn.execute(
            """
            SELECT
              v.video_id,
              v.instance_domain,
              v.title,
              v.description,
              v.tags_json,
              v.category,
              v.channel_name,
              v.comments_count
            FROM videos v
            """
        )
    else:
        logging.info("scanning for videos without embeddings")
        cursor = conn.execute(
            """
            SELECT
              v.video_id,
              v.instance_domain,
              v.title,
              v.description,
              v.tags_json,
              v.category,
              v.channel_name,
              v.comments_count
            FROM videos v
            LEFT JOIN video_embeddings e
              ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
            WHERE e.video_id IS NULL
            """
        )

    total_seen = 0
    total_inserted = 0
    total_skipped_empty = 0
    batch_index = 0
    embeddings_count = 0 if args.force else existing_embeddings

    while True:
        rows = cursor.fetchmany(args.batch_size)
        if not rows:
            break

        batch_index += 1
        total_seen += len(rows)
        texts: list[str] = []
        ids: list[tuple[str, str]] = []
        for row in rows:
            text = build_text(row)
            if text is None:
                total_skipped_empty += 1
                continue
            texts.append(text)
            ids.append((row["video_id"], row["instance_domain"]))

        if not texts:
            logging.info("batch skipped index=%d reason=empty_texts", batch_index)
            logging.info(
                "progress seen=%d inserted=%d skipped_empty=%d",
                total_seen,
                total_inserted,
                total_skipped_empty,
            )
            continue

        embeddings = model.encode(
            texts,
            batch_size=args.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        created_at = datetime.now(timezone.utc).isoformat()
        rows_to_insert = []
        for (video_id, instance_domain), embedding in zip(ids, embeddings):
            embedding = np.asarray(embedding, dtype=np.float32)
            rows_to_insert.append(
                (
                    video_id,
                    instance_domain,
                    embedding.tobytes(),
                    int(embedding.shape[0]),
                    args.model_name,
                    created_at,
                )
            )

        conn.executemany(
            """
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )
        conn.commit()
        total_inserted += len(rows_to_insert)
        embeddings_count += len(rows_to_insert)
        logging.info("progress embeddings=%d total_videos=%d", embeddings_count, total_videos)

    conn.close()
    logging.info("done embeddings=%d total_videos=%d", embeddings_count, total_videos)


if __name__ == "__main__":
    main()
