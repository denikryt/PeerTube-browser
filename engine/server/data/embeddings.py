"""Provide embeddings runtime helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import numpy as np


def parse_vector(raw: str | None) -> np.ndarray:
    """Parse a vector string or JSON array into a float32 array."""
    if raw is None:
        return np.array([], dtype=np.float32)
    trimmed = str(raw).strip()
    if not trimmed:
        return np.array([], dtype=np.float32)
    if trimmed.startswith("["):
        try:
            parsed = json.loads(trimmed)
        except json.JSONDecodeError:
            return np.array([], dtype=np.float32)
        if not isinstance(parsed, list):
            return np.array([], dtype=np.float32)
        values = [float(item) for item in parsed if _is_number(item)]
    else:
        parts = [part for part in trimmed.replace("\n", " ").split() if part]
        values = []
        for part in parts:
            for item in part.split(","):
                if not item:
                    continue
                if _is_number(item):
                    values.append(float(item))
    return np.array(values, dtype=np.float32)


def _is_number(value: Any) -> bool:
    """Return True if the value is numeric and finite."""
    try:
        return np.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def normalize_vector(values: np.ndarray) -> np.ndarray:
    """Return a normalized copy of the input vector."""
    if values.size == 0:
        return values
    norm = np.linalg.norm(values)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("Vector norm is zero")
    normalized = values / norm
    return normalized.astype(np.float32, copy=False)


def resolve_seed(
    conn: sqlite3.Connection,
    embeddings_dim: int,
    vector_param: str | None,
    video_id: str | None,
    host: str | None,
    uuid: str | None,
) -> dict[str, Any]:
    """Resolve a query seed from vector input or a video reference."""
    if vector_param:
        parsed = parse_vector(vector_param)
        if parsed.size == 0:
            raise ValueError("Invalid vector parameter")
        norm = np.linalg.norm(parsed)
        if not np.isfinite(norm) or norm == 0:
            return {"vector": None, "exclude_index_id": None, "meta": {"vector": "zero"}, "random": True}
        normalized = normalize_vector(parsed)
        if embeddings_dim and normalized.shape[0] != embeddings_dim:
            raise ValueError("Vector dimension does not match embeddings")
        return {
            "vector": normalized,
            "exclude_index_id": None,
            "meta": {"vector": True},
            "random": False,
        }

    seed = fetch_seed_embedding(conn, video_id, host, uuid)
    if not seed:
        return {"vector": None, "exclude_index_id": None, "meta": None}
    return {
        "vector": seed["embedding"],
        "exclude_index_id": seed["index_id"],
        "embedding": seed["embedding"],
        "index_id": seed["index_id"],
        "channel_id": seed.get("channel_id"),
        "instance_domain": seed["instance_domain"],
        "meta": {
            "video_id": seed["video_id"],
            "instance_domain": seed["instance_domain"],
            "channel_id": seed.get("channel_id"),
            "title": seed["title"],
        },
        "random": False,
    }


def fetch_seed_embedding(
    conn: sqlite3.Connection, video_id: str | None, host: str | None, uuid: str | None
) -> dict[str, Any] | None:
    """Fetch a single seed embedding and its metadata."""
    if uuid:
        seed = _fetch_seed_by_uuid(conn, uuid, host)
        if seed is not None:
            return seed
    if video_id:
        return _fetch_seed_by_id(conn, video_id, host)
    return None


def _fetch_seed_by_uuid(
    conn: sqlite3.Connection, uuid: str, host: str | None
) -> dict[str, Any] | None:
    """Handle fetch seed by uuid."""
    sql = """
        SELECT
          vii.index_id AS index_id,
          v.video_id,
          v.video_uuid,
          v.channel_id,
          v.instance_domain,
          v.title,
          e.embedding,
          e.embedding_dim
        FROM video_embeddings e
        JOIN video_index_ids vii
          ON vii.video_id = e.video_id AND vii.instance_domain = e.instance_domain AND vii.is_active = 1
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        WHERE v.video_uuid = ?
    """
    params: list[Any] = [uuid]
    if host is not None:
        sql += " AND v.instance_domain = ?"
        params.append(host)
    sql += " LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return _seed_from_row(row)


def _fetch_seed_by_id(
    conn: sqlite3.Connection, video_id: str, host: str | None
) -> dict[str, Any] | None:
    """Handle fetch seed by id."""
    sql = """
        SELECT
          vii.index_id AS index_id,
          v.video_id,
          v.video_uuid,
          v.channel_id,
          v.instance_domain,
          v.title,
          e.embedding,
          e.embedding_dim
        FROM video_embeddings e
        JOIN video_index_ids vii
          ON vii.video_id = e.video_id AND vii.instance_domain = e.instance_domain AND vii.is_active = 1
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        WHERE v.video_id = ?
    """
    params: list[Any] = [video_id]
    if host is not None:
        sql += " AND v.instance_domain = ?"
        params.append(host)
    sql += " LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return _seed_from_row(row)


def _seed_from_row(
    row: sqlite3.Row | None, *, require_embedding: bool = True
) -> dict[str, Any] | None:
    """Handle seed from row."""
    if not row:
        return None
    keys = set(row.keys())
    seed = {
        "video_id": row["video_id"],
        "video_uuid": row["video_uuid"],
        "channel_id": row["channel_id"],
        "instance_domain": row["instance_domain"],
        "title": row["title"],
    }
    if "index_id" in keys:
        seed["index_id"] = int(row["index_id"])
    if "embedding" not in keys or "embedding_dim" not in keys:
        return None if require_embedding else seed
    embedding = np.frombuffer(row["embedding"], dtype=np.float32)
    if embedding.size == 0 or embedding.shape[0] != row["embedding_dim"]:
        return None if require_embedding else seed
    seed["embedding"] = embedding
    return seed


def fetch_seed_embeddings_for_likes(
    conn: sqlite3.Connection,
    likes: list[dict[str, Any]],
    *,
    include_embedding: bool = True,
) -> dict[str, dict[str, Any]]:
    """Fetch seed embeddings for a list of likes in a single batch."""
    if not likes:
        return {}
    uuid_pairs: list[tuple[str, str]] = []
    id_pairs: list[tuple[str, str]] = []
    for like in likes:
        instance = like.get("instance_domain") or ""
        uuid = like.get("video_uuid")
        video_id = like.get("video_id")
        if uuid:
            uuid_pairs.append((str(uuid), str(instance)))
        if video_id:
            id_pairs.append((str(video_id), str(instance)))

    needs_embedding = bool(include_embedding)
    embedding_select = ",\n              e.embedding,\n              e.embedding_dim" if needs_embedding else ""
    embedding_join = """
            JOIN video_embeddings e
              ON e.video_id = v.video_id
             AND e.instance_domain = v.instance_domain
    """ if needs_embedding else ""
    index_select = ",\n              vii.index_id AS index_id" if needs_embedding else ""
    index_join = """
            JOIN video_index_ids vii
              ON vii.video_id = v.video_id
             AND vii.instance_domain = v.instance_domain
             AND vii.is_active = 1
    """ if needs_embedding else ""

    rows: list[sqlite3.Row] = []
    if uuid_pairs:
        # Start from the tiny request-local input set and join into the indexed
        # video identity tables. The old tuple-IN form allowed SQLite to choose
        # a large-table plan on million-row databases, which made the cached
        # recommendation seed lookup dominate request latency.
        placeholders = ", ".join(["(?, ?)"] * len(uuid_pairs))
        params: list[Any] = []
        for uuid, instance in uuid_pairs:
            params.extend([uuid, instance])
        rows += conn.execute(
            f"""
            WITH wanted(video_uuid, instance_domain) AS (VALUES {placeholders})
            SELECT
              v.video_id,
              v.video_uuid,
              v.channel_id,
              v.instance_domain,
              v.title{index_select}{embedding_select}
            FROM wanted w
            JOIN videos v
              ON v.video_uuid = w.video_uuid
             AND v.instance_domain = w.instance_domain
            {embedding_join}
            {index_join}
            """,
            params,
        ).fetchall()

    if id_pairs:
        placeholders = ", ".join(["(?, ?)"] * len(id_pairs))
        params = []
        for video_id, instance in id_pairs:
            params.extend([video_id, instance])
        rows += conn.execute(
            f"""
            WITH wanted(video_id, instance_domain) AS (VALUES {placeholders})
            SELECT
              v.video_id,
              v.video_uuid,
              v.channel_id,
              v.instance_domain,
              v.title{index_select}{embedding_select}
            FROM wanted w
            JOIN videos v
              ON v.video_id = w.video_id
             AND v.instance_domain = w.instance_domain
            {embedding_join}
            {index_join}
            """,
            params,
        ).fetchall()

    seeds: dict[str, dict[str, Any]] = {}
    for row in rows:
        seed = _seed_from_row(row, require_embedding=needs_embedding)
        if not seed:
            continue
        instance = seed.get("instance_domain") or ""
        video_id = seed.get("video_id") or ""
        seeds[f"{video_id}::{instance}"] = seed
        if seed.get("video_uuid"):
            seeds[f"uuid::{seed['video_uuid']}::{instance}"] = seed
    return seeds


def fetch_embeddings_by_ids(
    conn: sqlite3.Connection, entries: list[dict[str, Any]]
) -> dict[str, np.ndarray]:
    """Fetch embeddings for (video_id, instance_domain) pairs.

    Recommendation layers may request embeddings for thousands of candidate
    rows. Use a VALUES table joined against the composite primary key instead
    of a large OR chain; the OR form becomes very slow on real SQLite datasets
    after the stable index-id migration added extra joins in adjacent paths.

    ``video_index_ids`` is intentionally not joined here. This helper resolves
    embeddings for already-selected video rows; artifact eligibility is enforced
    when ANN/random artifacts are built and when index ids are resolved.
    """
    if not entries:
        return {}
    result: dict[str, np.ndarray] = {}
    seen: set[tuple[str, str]] = set()
    normalized: list[tuple[str, str]] = []
    for entry in entries:
        video_id = entry.get("video_id")
        if not video_id:
            continue
        pair = (str(video_id), str(entry.get("instance_domain") or ""))
        if pair in seen:
            continue
        seen.add(pair)
        normalized.append(pair)
    if not normalized:
        return {}

    for batch in _chunk(normalized, 500):
        values_sql = ", ".join(["(?, ?)"] * len(batch))
        params: list[Any] = []
        for video_id, instance_domain in batch:
            params.extend([video_id, instance_domain])
        rows = conn.execute(
            f"""
            WITH requested(video_id, instance_domain) AS (
              VALUES {values_sql}
            )
            SELECT
              e.video_id,
              e.instance_domain,
              e.embedding,
              e.embedding_dim
            FROM requested r
            JOIN video_embeddings e
              ON e.video_id = r.video_id
             AND e.instance_domain = r.instance_domain
            """,
            params,
        ).fetchall()
        for row in rows:
            embedding = np.frombuffer(row["embedding"], dtype=np.float32)
            if embedding.size == 0 or embedding.shape[0] != row["embedding_dim"]:
                continue
            result[f"{row['video_id']}::{row['instance_domain'] or ''}"] = embedding
    return result


def _chunk(values: list[Any], size: int) -> list[list[Any]]:
    """Handle chunk."""
    return [values[index : index + size] for index in range(0, len(values), size)]
