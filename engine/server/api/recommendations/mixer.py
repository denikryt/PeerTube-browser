"""Provide mixer runtime helpers."""

from __future__ import annotations

import logging
import math
import random
from time import perf_counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from data.time import now_ms
from recommendations.profile import resolve_profile_config_with_guest
from recommendations.scoring import build_scoring_settings, score_candidate

class CandidateGenerator(Protocol):
    """Represent candidate generator behavior."""
    name: str

    def get_candidates(
        self,
        server: Any,
        user_id: str,
        limit: int,
        refresh_cache: bool = False,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return candidates from this generator."""
        raise NotImplementedError


@dataclass(frozen=True)
class MixerDeps:
    """Represent mixer deps behavior."""
    like_key: Callable[[Any], str]
    fetch_recent_likes: Callable[[str, int], list[dict[str, Any]]]
    max_likes: int


class MixingRecommendationStrategy:
    """Represent mixing recommendation strategy behavior."""
    name = "mixed"

    def __init__(
        self,
        generators: dict[str, CandidateGenerator],
        config: dict[str, Any],
        deps: MixerDeps,
    ) -> None:
        """Initialize the instance."""
        self.generators = generators
        self.config = config
        self.deps = deps

    def generate_recommendations(
        self,
        server: Any,
        user_id: str,
        limit: int,
        refresh_cache: bool = False,
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        """Handle generate recommendations."""
        recent_likes = self.deps.fetch_recent_likes(user_id, self.deps.max_likes)
        likes_available = bool(recent_likes)
        profile_name, profile_config = resolve_profile_config_with_guest(
            self.config, mode, likes_available
        )
        configured_batch = int(profile_config.get("batch_size") or 0)
        if configured_batch < 0:
            configured_batch = 0
        request_limit = max(int(limit or 0), 0)
        if configured_batch > 0:
            batch_size = min(request_limit or configured_batch, configured_batch)
        else:
            batch_size = request_limit
        if batch_size <= 0:
            return []

        generator_configs = profile_config.get("generators", profile_config.get("layers", {}))
        generator_order = self._resolve_order(profile_config, generator_configs)
        recent_likes = self.deps.fetch_recent_likes(user_id, self.deps.max_likes)
        likes_available = bool(recent_likes)
        generator_limits = self._resolve_fetch_limits(
            generator_configs, generator_order, batch_size, profile_config, likes_available
        )
        if not generator_configs:
            return []

        candidates_by_layer: dict[str, list[dict[str, Any]]] = {}
        layer_timings: list[str] = []
        for name in generator_order:
            if name not in generator_limits:
                continue
            generator = self.generators.get(name)
            if generator is None:
                continue
            fetch_limit = int(generator_limits[name])
            if fetch_limit <= 0:
                continue
            layer_start = perf_counter()
            candidates = generator.get_candidates(
                server,
                user_id,
                fetch_limit,
                refresh_cache,
                config=generator_configs.get(name, {}),
            )
            layer_ms = int((perf_counter() - layer_start) * 1000)
            if generator_configs.get(name, {}).get("shuffle"):
                random.shuffle(candidates)
            candidates_by_layer[name] = candidates
            layer_timings.append(f"{name}={layer_ms}ms({len(candidates)})")

        if layer_timings:
            logging.info("[recommendations] layer timing: %s", " ".join(layer_timings))

        seen_keys = {self.deps.like_key(entry) for entry in recent_likes}
        logging.info(
            "[recommendations] profile=%s likes=%s",
            profile_name,
            "yes" if likes_available else "no",
        )
        return self._soft_mix_candidates(
            candidates_by_layer,
            generator_configs,
            generator_order,
            batch_size,
            seen_keys,
            profile_config,
            profile_name,
        )

    def _resolve_order(
        self, profile_config: dict[str, Any], layer_configs: dict[str, Any]
    ) -> list[str]:
        """Handle resolve order."""
        configured_order = profile_config.get("mixing", {}).get("order")
        if configured_order:
            return [name for name in configured_order if name in layer_configs]
        return list(layer_configs.keys())

    def _resolve_fetch_limits(
        self,
        layer_configs: dict[str, Any],
        layer_order: Iterable[str],
        batch_size: int,
        profile_config: dict[str, Any],
        has_likes: bool,
    ) -> dict[str, int]:
        """Handle resolve fetch limits."""
        enabled_layers = []
        for name in layer_order:
            config = layer_configs.get(name, {})
            if not config.get("enabled", True):
                continue
            if config.get("requires_likes") and not has_likes:
                continue
            enabled_layers.append(name)
        if not enabled_layers:
            return {}

        overfetch_factor = float(profile_config.get("overfetch_factor") or 1)
        overfetch_factor = max(overfetch_factor, 1)
        limits: dict[str, int] = {}
        remaining = int(batch_size * overfetch_factor)
        ratio_by_layer: dict[str, float] = {}
        total_ratio = 0.0

        for name in enabled_layers:
            config = layer_configs.get(name, {})
            ratio = float(config.get("gather_ratio") or 0.0)
            ratio_by_layer[name] = ratio
            total_ratio += ratio
        ratio_layers = [name for name in enabled_layers if ratio_by_layer.get(name, 0.0) > 0.0]

        if remaining <= 0:
            return limits

        if total_ratio <= 0 and enabled_layers:
            per_layer = max(remaining // len(enabled_layers), 1)
            for name in enabled_layers:
                limits[name] = per_layer

        if total_ratio > 0 and ratio_layers:
            allocated = 0
            for name in ratio_layers:
                ratio = ratio_by_layer.get(name, 0.0)
                share = int((remaining * ratio) // total_ratio)
                limits[name] = share
                allocated += share

            remainder = remaining - allocated
            for name in ratio_layers:
                if remainder <= 0:
                    break
                limits[name] += 1
                remainder -= 1

        return limits

    def _resolve_output_targets(
        self,
        layer_configs: dict[str, Any],
        layer_order: Iterable[str],
        batch_size: int,
    ) -> dict[str, int]:
        """Handle resolve output targets."""
        enabled_layers = [
            name
            for name in layer_order
            if layer_configs.get(name, {}).get("enabled", True)
        ]
        if not enabled_layers or batch_size <= 0:
            return {}

        targets: dict[str, int] = {}
        remaining = int(batch_size)
        ratio_by_layer: dict[str, float] = {}
        total_ratio = 0.0

        for name in enabled_layers:
            config = layer_configs.get(name, {})
            ratio = float(config.get("mix_ratio") or 0.0)
            ratio_by_layer[name] = ratio
            total_ratio += ratio
        ratio_layers = [name for name in enabled_layers if ratio_by_layer.get(name, 0.0) > 0.0]

        if remaining <= 0:
            return targets

        if total_ratio <= 0 and enabled_layers:
            per_layer = remaining // len(enabled_layers)
            for name in enabled_layers:
                targets[name] = per_layer
            remainder = remaining - (per_layer * len(enabled_layers))
            for name in enabled_layers:
                if remainder <= 0:
                    break
                targets[name] += 1
                remainder -= 1

        if total_ratio > 0 and ratio_layers:
            allocated = 0
            for name in ratio_layers:
                ratio = ratio_by_layer.get(name, 0.0)
                share = int((remaining * ratio) // total_ratio)
                targets[name] = share
                allocated += share

            remainder = remaining - allocated
            for name in ratio_layers:
                if remainder <= 0:
                    break
                targets[name] += 1
                remainder -= 1

        return targets

    def _build_layer_schedule(
        self,
        targets: dict[str, int],
        layer_order: Iterable[str],
    ) -> list[str]:
        """Handle build layer schedule."""
        if not targets:
            return []
        schedule: list[str] = []
        counts = {name: 0 for name in targets}
        total = sum(targets.values())
        ordered_layers = [name for name in layer_order if name in targets]
        for _ in range(total):
            chosen = None
            chosen_ratio = None
            for name in ordered_layers:
                target = targets.get(name, 0)
                if target <= 0:
                    continue
                if counts.get(name, 0) >= target:
                    continue
                ratio = counts.get(name, 0) / target
                if chosen is None or ratio < (chosen_ratio or 0):
                    chosen = name
                    chosen_ratio = ratio
            if chosen is None:
                break
            counts[chosen] = counts.get(chosen, 0) + 1
            schedule.append(chosen)
        return schedule

    def _soft_mix_candidates(
        self,
        candidates_by_layer: dict[str, list[dict[str, Any]]],
        generator_configs: dict[str, Any],
        layer_order: Iterable[str],
        batch_size: int,
        seen_keys: set[str],
        profile_config: dict[str, Any],
        profile_name: str,
    ) -> list[dict[str, Any]]:
        """Handle soft mix candidates."""
        if not candidates_by_layer:
            return []

        layer_order = list(layer_order)
        settings = build_scoring_settings(profile_config)
        now_ms_value = now_ms()
        scoring_start = perf_counter()
        scored_pool: list[tuple[str | None, dict[str, Any]]] = []
        similarity_values: list[float] = []
        explore_cfg = generator_configs.get("explore", {})
        explore_min = float(explore_cfg.get("similarity_min") or explore_cfg.get("explore_min") or 0.0)
        explore_max = float(explore_cfg.get("similarity_max") or explore_cfg.get("explore_max") or 1.0)

        for name in layer_order:
            for candidate in candidates_by_layer.get(name, []):
                score_candidate(candidate, settings, layer_name=name, now_ms_value=now_ms_value)
                scored_pool.append((name, candidate))
                raw_similarity = candidate.get("similarity_score")
                try:
                    similarity = float(raw_similarity)
                except (TypeError, ValueError):
                    similarity = None
                if similarity is not None and math.isfinite(similarity):
                    similarity_values.append(similarity)

        similarity_pool_min = min(similarity_values) if similarity_values else None
        similarity_pool_max = max(similarity_values) if similarity_values else None
        scoring_ms = int((perf_counter() - scoring_start) * 1000)
        logging.info(
            "[recommendations] similarity pool: min=%s max=%s count=%d",
            f"{similarity_pool_min:.6f}" if similarity_pool_min is not None else "n/a",
            f"{similarity_pool_max:.6f}" if similarity_pool_max is not None else "n/a",
            len(similarity_values),
        )

        for layer, candidate in scored_pool:
            candidate["debug_similarity_pool_min"] = similarity_pool_min
            candidate["debug_similarity_pool_max"] = similarity_pool_max
            candidate["debug_explore_min"] = explore_min
            candidate["debug_explore_max"] = explore_max
            candidate["debug_profile"] = profile_name

        active_layers = [name for name in layer_order if candidates_by_layer.get(name)]
        if not active_layers:
            return []
        targets = self._resolve_output_targets(generator_configs, active_layers, batch_size)
        layered: dict[str, list[tuple[str | None, dict[str, Any]]]] = {}
        for layer, candidate in scored_pool:
            if layer is None:
                continue
            layered.setdefault(layer, []).append((layer, candidate))

        for layer, items in layered.items():
            items.sort(key=lambda item: float(item[1].get("score") or 0.0), reverse=True)
            for index, item in enumerate(items):
                item[1]["debug_rank_before"] = index + 1

        for layer in list(targets.keys()):
            targets[layer] = min(targets[layer], len(layered.get(layer, [])))

        mix_start = perf_counter()
        schedule = self._build_layer_schedule(targets, layer_order)
        remaining_by_layer = {
            layer: list(items) for layer, items in layered.items()
        }
        mixed_pool: list[tuple[str | None, dict[str, Any]]] = []
        for layer in schedule:
            if len(mixed_pool) >= batch_size:
                break
            items = remaining_by_layer.get(layer, [])
            if not items:
                continue
            mixed_pool.append(items.pop(0))

        if len(mixed_pool) < batch_size:
            for layer in layer_order:
                if len(mixed_pool) >= batch_size:
                    break
                items = remaining_by_layer.get(layer, [])
                while items and len(mixed_pool) < batch_size:
                    mixed_pool.append(items.pop(0))
        mix_ms = int((perf_counter() - mix_start) * 1000)

        post_start = perf_counter()
        output = self._apply_post_filters(mixed_pool, batch_size, seen_keys, profile_config)
        post_ms = int((perf_counter() - post_start) * 1000)

        logging.info(
            "[recommendations] timing scoring=%dms mix=%dms post=%dms total=%dms",
            scoring_ms,
            mix_ms,
            post_ms,
            scoring_ms + mix_ms + post_ms,
        )
        return output

    def _apply_post_filters(
        self,
        ranked_pool: list[tuple[str | None, dict[str, Any]]],
        batch_size: int,
        seen_keys: set[str],
        profile_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Handle apply post filters."""
        output: list[dict[str, Any]] = []
        layer_counts: dict[str, int] = {}
        skip_counts = {
            "seen": 0,
            "layer_cap": 0,
        }

        soft_caps = profile_config.get("soft_caps", {})
        min_caps = {str(k): int(v) for k, v in (soft_caps.get("min") or {}).items()}
        max_caps = {str(k): int(v) for k, v in (soft_caps.get("max") or {}).items()}

        def can_take(layer: str | None, candidate: dict[str, Any]) -> bool:
            """Check whether can take."""
            key = self.deps.like_key(candidate)
            if key in seen_keys:
                skip_counts["seen"] += 1
                return False
            if layer:
                if layer in max_caps and max_caps[layer] > 0:
                    if layer_counts.get(layer, 0) >= max_caps[layer]:
                        skip_counts["layer_cap"] += 1
                        return False
            return True

        def take(layer: str | None, candidate: dict[str, Any]) -> None:
            """Handle take."""
            key = self.deps.like_key(candidate)
            seen_keys.add(key)
            if layer:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
            output.append(candidate)

        if min_caps:
            for layer, min_count in min_caps.items():
                if min_count <= 0:
                    continue
                for pool_layer, candidate in ranked_pool:
                    if len(output) >= batch_size:
                        break
                    if pool_layer != layer:
                        continue
                    if layer_counts.get(layer, 0) >= min_count:
                        break
                    if not can_take(pool_layer, candidate):
                        continue
                    take(pool_layer, candidate)

        if len(output) >= batch_size:
            return output[:batch_size]

        for layer, candidate in ranked_pool:
            if len(output) >= batch_size:
                break
            if not can_take(layer, candidate):
                continue
            take(layer, candidate)

        for index, candidate in enumerate(output):
            candidate["debug_rank_after"] = index + 1

        logging.info(
            "[recommendations] post-filters kept=%d/%d pool=%d skipped seen=%d layer_cap=%d",
            len(output),
            batch_size,
            len(ranked_pool),
            skip_counts["seen"],
            skip_counts["layer_cap"],
        )
        return output
