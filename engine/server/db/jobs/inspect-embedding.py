#!/usr/bin/env python3
import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one embedding from sqlite.")
    repo_root = Path(__file__).resolve().parents[4]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    parser.add_argument(
        "--db-path",
        default=str(default_db),
        help="Path to sqlite database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Number of rows to print.",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    cursor = conn.execute(
        "SELECT embedding, embedding_dim, model_name, video_id, instance_domain "
        "FROM video_embeddings LIMIT ?",
        (args.limit,),
    )
    for embedding_blob, embedding_dim, model_name, video_id, instance_domain in cursor:
        embedding = np.frombuffer(embedding_blob, dtype=np.float32)
        print(
            f"video_id={video_id} instance_domain={instance_domain} "
            f"model={model_name} dim={embedding_dim} "
            f"shape={embedding.shape} sample={embedding[:10].tolist()}"
        )
    conn.close()


if __name__ == "__main__":
    main()
