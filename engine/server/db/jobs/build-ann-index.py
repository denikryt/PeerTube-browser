#!/usr/bin/env python3
"""Build a FAISS ANN index from video_embeddings in a SQLite database."""
import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter

try:
    import faiss  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is required. Install faiss-cpu in your Python environment."
    ) from exc


@dataclass
class EmbeddingRow:
    rowid: int
    embedding: np.ndarray


def iter_embeddings(
    conn: sqlite3.Connection,
    query: str,
    params: tuple,
    dim: int,
    batch_size: int,
) -> Iterable[list[EmbeddingRow]]:
    cursor = conn.execute(query, params)
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        batch: list[EmbeddingRow] = []
        for rowid, embedding_blob, embedding_dim in rows:
            if embedding_dim != dim:
                continue
            embedding = np.frombuffer(embedding_blob, dtype=np.float32)
            if embedding.shape[0] != dim:
                continue
            batch.append(EmbeddingRow(rowid=rowid, embedding=embedding))
        if batch:
            yield batch


def fetch_training_samples(
    conn: sqlite3.Connection,
    dim: int,
    sample_size: int,
) -> np.ndarray:
    total = conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone()[0]
    if total == 0:
        raise RuntimeError("No embeddings found.")
    step = max(total // sample_size, 1)
    cursor = conn.execute(
        """
        SELECT rowid, embedding, embedding_dim
        FROM video_embeddings
        WHERE (rowid % ?) = 0
        LIMIT ?
        """,
        (step, sample_size),
    )
    vectors: list[np.ndarray] = []
    for rowid, embedding_blob, embedding_dim in cursor:
        if embedding_dim != dim:
            continue
        embedding = np.frombuffer(embedding_blob, dtype=np.float32)
        if embedding.shape[0] != dim:
            continue
        vectors.append(embedding)
    if not vectors:
        raise RuntimeError("No training samples found.")
    return np.vstack(vectors)


def normalize_vectors(vectors: np.ndarray) -> None:
    faiss.normalize_L2(vectors)


def build_index(
    dim: int,
    nlist: int,
    m: int,
    nbits: int,
) -> faiss.Index:
    if dim % m != 0:
        raise ValueError(f"dim={dim} must be divisible by m={m} for PQ")
    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFPQ(
        quantizer, dim, nlist, m, nbits, faiss.METRIC_INNER_PRODUCT
    )
    return faiss.IndexIDMap2(index)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a FAISS ANN index from existing video embeddings.",
        formatter_class=CompactHelpFormatter,
    )
    repo_root = Path(__file__).resolve().parents[4]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    default_index = repo_root / "engine" / "server" / "db" / "video-embeddings.faiss"
    default_meta = repo_root / "engine" / "server" / "db" / "video-embeddings.faiss.json"
    parser.add_argument(
        "--db-path",
        default=str(default_db),
        help="Path to sqlite database.",
    )
    parser.add_argument(
        "--index-path",
        default=str(default_index),
        help="Path to write FAISS index.",
    )
    parser.add_argument(
        "--meta-path",
        default=str(default_meta),
        help="Path to write index metadata.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help=(
            "Batch size for loading embeddings into memory; higher is faster but uses more RAM."
        ),
    )
    parser.add_argument(
        "--train-sample",
        type=int,
        default=200000,
        help=(
            "Training sample size for the IVFPQ index; larger usually improves recall but takes longer."
        ),
    )
    parser.add_argument(
        "--nlist",
        type=int,
        default=4096,
        help=(
            "Number of inverted lists; larger can improve recall but increases training time and index size."
        ),
    )
    parser.add_argument(
        "--m",
        type=int,
        default=32,
        help=(
            "Number of PQ sub-quantizers; higher improves accuracy but increases index size and build time."
        ),
    )
    parser.add_argument(
        "--nbits",
        type=int,
        default=8,
        help=(
            "Bits per PQ code; higher improves accuracy but increases index size."
        ),
    )
    accel_group = parser.add_mutually_exclusive_group()
    accel_group.add_argument(
        "--gpu",
        dest="use_gpu",
        action="store_true",
        help="Build/train ANN index on GPU. Fails if FAISS GPU bindings are unavailable.",
    )
    accel_group.add_argument(
        "--cpu",
        dest="use_gpu",
        action="store_false",
        help="Build/train ANN index on CPU.",
    )
    parser.set_defaults(use_gpu=False)
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="L2-normalize vectors before indexing (useful for inner-product search).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = Path(args.db_path)
    index_path = Path(args.index_path)
    meta_path = Path(args.meta_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT embedding_dim, model_name FROM video_embeddings LIMIT 1"
    ).fetchone()
    if not row:
        raise RuntimeError("No embeddings found in database.")
    dim = int(row["embedding_dim"])
    model_name = row["model_name"]

    total = conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone()[0]
    logging.info("embeddings=%d dim=%d", total, dim)

    logging.info("sampling training vectors=%d", args.train_sample)
    train_vectors = fetch_training_samples(conn, dim, args.train_sample)
    if args.normalize:
        normalize_vectors(train_vectors)

    logging.info(
        "building index nlist=%d m=%d nbits=%d mode=%s",
        args.nlist,
        args.m,
        args.nbits,
        "gpu" if args.use_gpu else "cpu",
    )
    cpu_index = build_index(dim, args.nlist, args.m, args.nbits)
    index = cpu_index
    gpu_resources = None
    if args.use_gpu:
        if not hasattr(faiss, "StandardGpuResources") or not hasattr(
            faiss, "index_cpu_to_gpu"
        ):
            raise RuntimeError(
                "GPU mode requested but installed FAISS has no GPU support. "
                "Install faiss-gpu (matching CUDA) or run with --cpu."
            )
        gpu_resources = faiss.StandardGpuResources()
        index = faiss.index_cpu_to_gpu(gpu_resources, 0, cpu_index)
    logging.info("training index")
    index.train(train_vectors)

    logging.info("adding vectors in batches size=%d", args.batch_size)
    added = 0
    query = "SELECT rowid, embedding, embedding_dim FROM video_embeddings"
    for batch in iter_embeddings(conn, query, (), dim, args.batch_size):
        ids = np.array([item.rowid for item in batch], dtype=np.int64)
        vectors = np.vstack([item.embedding for item in batch])
        if args.normalize:
            normalize_vectors(vectors)
        index.add_with_ids(vectors, ids)
        added += len(batch)
        if added % (args.batch_size * 10) == 0:
            logging.info("progress added=%d/%d", added, total)

    index_to_write = index
    if args.use_gpu:
        if not hasattr(faiss, "index_gpu_to_cpu"):
            raise RuntimeError(
                "GPU index built but FAISS is missing index_gpu_to_cpu()."
            )
        logging.info("transferring GPU index to CPU for serialization")
        index_to_write = faiss.index_gpu_to_cpu(index)

    logging.info("writing index to %s", index_path)
    faiss.write_index(index_to_write, str(index_path))

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "total": added,
        "embedding_dim": dim,
        "model_name": model_name,
        "index_type": "IVFPQ",
        "nlist": args.nlist,
        "m": args.m,
        "nbits": args.nbits,
        "normalized": bool(args.normalize),
        "acceleration": "gpu" if args.use_gpu else "cpu",
        "id_source": "video_embeddings.rowid",
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    conn.close()
    logging.info("done index=%s entries=%d", index_path, added)


if __name__ == "__main__":
    main()
