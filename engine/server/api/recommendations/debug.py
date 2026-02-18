"""Provide debug runtime helpers."""

from __future__ import annotations

from typing import Any


def attach_debug_info(
    stable_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach debug metadata to stable rows by index."""
    output: list[dict[str, Any]] = []
    for index, stable in enumerate(stable_rows):
        source = source_rows[index] if index < len(source_rows) else {}
        debug = {
            "score": source.get("score"),
            "similarity_score": source.get("similarity_score"),
            "similarity_pool_min": source.get("debug_similarity_pool_min"),
            "similarity_pool_max": source.get("debug_similarity_pool_max"),
            "freshness_score": source.get("debug_freshness_score"),
            "popularity_score": source.get("debug_popularity_score"),
            "layer": source.get("debug_layer"),
            "rank_before": source.get("debug_rank_before"),
            "rank_after": source.get("debug_rank_after"),
            "profile": source.get("debug_profile"),
            "explore_min": source.get("debug_explore_min"),
            "explore_max": source.get("debug_explore_max"),
            "explore_empty": source.get("debug_explore_empty"),
            "explore_pool_size": source.get("debug_explore_pool_size"),
            "explore_in_range": source.get("debug_explore_in_range"),
            "exploit_pool_size": source.get("debug_exploit_pool_size"),
            "exploit_in_range": source.get("debug_exploit_in_range"),
        }
        output.append({**stable, "debug": debug})
    return output
