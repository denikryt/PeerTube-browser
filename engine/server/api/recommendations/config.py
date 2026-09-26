"""Own recommendation pipeline defaults and validation.

This module is the recommendation-domain source of truth for the checked-in
Python configuration. Stage 5 intentionally keeps runtime execution on the raw
dictionary while adding validation so existing generator and mixer semantics do
not change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

try:
    from recommendations.types import (
        ValidatedGeneratorConfig,
        ValidatedProfileConfig,
        ValidatedRecommendationConfig,
    )
except ModuleNotFoundError:  # pragma: no cover - package import fallback.
    from engine.server.api.recommendations.types import (
        ValidatedGeneratorConfig,
        ValidatedProfileConfig,
        ValidatedRecommendationConfig,
    )


class RecommendationConfigError(ValueError):
    """Raised when checked-in recommendation configuration is structurally invalid."""


ALLOWED_GENERATORS = frozenset({"random", "popular", "explore", "exploit", "fresh"})
_LIMIT_KEYS = frozenset({
    "pool_size",
    "max_per_instance",
    "max_per_author",
    "similarity_min",
    "similarity_max",
    "exploit_min",
    "explore_min",
})
_RATIO_KEYS = frozenset({"gather_ratio", "mix_ratio"})


# Pool size for popular candidates (0 uses per-request limit).
DEFAULT_POPULAR_POOL_SIZE = 5000
# Pool size for fresh candidates (0 uses DEFAULT_SIMILAR_PER_LIKE).
DEFAULT_FRESH_POOL_SIZE = 5000

# Recommendation pipeline configuration and batch sizing.
# Notes:
# - Profiles allow distinct behavior for "home" (no seed) and "upnext" (seed).
# - gather_ratio sets candidate fetch share; mix_ratio sets output mix.
# - fallback behavior applies when a layer is short.
# - overfetch_factor inflates per-layer fetch sizes to survive filters/dedup.
# - scoring combines similarity/freshness/popularity (+ layer bonus) into final score.
# - layers (explore/exploit/fresh) are mixed by configured ratios with fallback order.
# - soft_caps are applied after mixing to enforce diversity constraints.

RECOMMENDATION_PIPELINE = {
    "default_profile": "home",
    "profiles": {
        "home": {
            # Total items returned per feed batch.
            "batch_size": 48,

            # Fetch extra per layer to improve fill rate after filtering/dedup.
            # 2 means "fetch ~2x more than needed per layer" to compensate for filters.
            "overfetch_factor": 1,
            "generators": {
                # gather_ratio controls candidate fetch share; mix_ratio controls output share.
                # shuffle applies within the generator pool before scoring.
                # enabled toggles generator participation.
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "below_explore_min": True,
                    "explore_min": 0.2,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "explore": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": 5000,
                    "similarity_min": 0.2,
                    "similarity_max": 0.4,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "exploit": {
                    "enabled": True,
                    "gather_ratio": 0.5,
                    "mix_ratio": 0.5,
                    "shuffle": True,
                    "pool_size": 2000,
                    "exploit_min": 0.4,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            # Order for candidate collection and fallback when a layer runs out.
            "mixing": {"order": ["explore", "exploit", "popular", "random", "fresh"]},
            # Scoring configuration for unified ranking.
            "scoring": {
                # Weights for feature aggregation into final score.
                # Higher weight = stronger influence on final order.
                # similarity=1.0 is the baseline; freshness/popularity are smaller nudges.
                "weights": {"similarity": 1.0, "freshness": 0.25, "popularity": 0.2},
                # Per-layer additive bonus to nudge sources up/down.
                # Example: exploit +0.15 shifts high-similarity candidates upward.
                "layer_weights": {
                    "exploit": 0.15,
                    "explore": 0.05,
                    "popular": 0.05,
                    "random": 0.0,
                    "fresh": 0.05,
                },
                # Half-life (days) for freshness decay.
                # 14 => score halves every ~14 days since publish.
                "freshness_half_life_days": 14,
                # Popularity feature weighting (log-normalized internally).
                # likes are weighted more than views in the popularity sub-score.
                "popularity": {"views": 1.0, "likes": 2.0},
            },
            # Optional caps and post-filters.
            # soft_caps.min/max are per-layer constraints applied after ranking.
            # fresh<=12 keeps fresh from dominating (even if scored high).
            "soft_caps": {"max": {"fresh": 12}},
            # post_filters removed: limits are enforced per-layer before mixing.
        },
        "guest_home": {
            "batch_size": 48,
            "overfetch_factor": 2,
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.6,
                    "mix_ratio": 0.6,
                    "shuffle": True,
                    "below_explore_min": False,
                    "explore_min": 0.2,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["popular", "random", "fresh"]},
            "scoring": {
                "weights": {"similarity": 0.2, "freshness": 0.35, "popularity": 0.45},
                "layer_weights": {"popular": 0.05, "random": 0.0, "fresh": 0.05},
                "freshness_half_life_days": 14,
                "popularity": {"views": 1.0, "likes": 2.0},
            },
            "soft_caps": {"max": {"fresh": 12}},
        },
        "upnext": {
            # Up Next uses the same layers but different scoring/ratios.
            "scoring": {
                # Bias more toward similarity, less toward freshness/popularity.
                "weights": {"similarity": 1.0, "freshness": 0.1, "popularity": 0.1},
                # Longer half-life => freshness decays slower for upnext.
                "freshness_half_life_days": 30,
                "popularity": {"views": 1.0, "likes": 1.0},
            },
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "below_explore_min": True,
                    "explore_min": 0.25,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "explore": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": 1200,
                    "similarity_min": 0.25,
                    "similarity_max": 0.55,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "exploit": {
                    "enabled": True,
                    "gather_ratio": 0.75,
                    "mix_ratio": 0.75,
                    "shuffle": True,
                    "pool_size": 2000,
                    "exploit_min": 0.7,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.05,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["explore", "exploit", "popular", "random", "fresh"]},
        },
        "guest_upnext": {
            "scoring": {
                "weights": {"similarity": 1.0, "freshness": 0.1, "popularity": 0.1},
                "freshness_half_life_days": 30,
                "popularity": {"views": 1.0, "likes": 1.0},
            },
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.4,
                    "mix_ratio": 0.4,
                    "shuffle": True,
                    "below_explore_min": False,
                    "explore_min": 0.25,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.4,
                    "mix_ratio": 0.4,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["popular", "random", "fresh"]},
        },
    },
}

# Default number of videos returned per feed batch.
BATCH_SIZE = RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]


# Default number of videos returned per feed batch.
BATCH_SIZE = RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]


def clone_recommendation_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a deep copy of a recommendation config without mutating input."""
    return deepcopy(dict(config or RECOMMENDATION_PIPELINE))


def validate_recommendation_config(config: Mapping[str, Any]) -> ValidatedRecommendationConfig:
    """Validate recommendation config shape while preserving raw runtime values."""
    if not isinstance(config, Mapping):
        raise RecommendationConfigError("config must be a mapping")
    profiles_raw = config.get("profiles")
    if profiles_raw is None:
        profiles_raw = {}
    if not isinstance(profiles_raw, Mapping):
        raise RecommendationConfigError("profiles must be a mapping")

    default_profile = config.get("default_profile")
    if default_profile is not None and not isinstance(default_profile, str):
        raise RecommendationConfigError("default_profile must be a string")
    if default_profile and default_profile not in profiles_raw:
        raise RecommendationConfigError(
            f"default_profile {default_profile!r} is missing from profiles"
        )

    profiles: dict[str, ValidatedProfileConfig] = {}
    for profile_name, profile_config in profiles_raw.items():
        if not isinstance(profile_name, str) or not profile_name:
            raise RecommendationConfigError("profiles keys must be non-empty strings")
        profiles[profile_name] = _validate_profile(profile_name, profile_config)

    return ValidatedRecommendationConfig(
        default_profile=default_profile,
        profiles=profiles,
        raw=config,
    )


def _validate_profile(name: str, profile_config: Any) -> ValidatedProfileConfig:
    """Validate a single profile and return typed metadata for safe introspection."""
    if not isinstance(profile_config, Mapping):
        raise RecommendationConfigError(f"profiles.{name} must be a mapping")

    batch_size = profile_config.get("batch_size")
    if batch_size is not None:
        if not isinstance(batch_size, int) or batch_size < 0:
            raise RecommendationConfigError(f"profiles.{name}.batch_size must be an integer >= 0")

    overfetch_factor = profile_config.get("overfetch_factor", 1)
    _require_non_negative_number(f"profiles.{name}.overfetch_factor", overfetch_factor)

    generators_raw = profile_config.get("generators", profile_config.get("layers", {}))
    if not isinstance(generators_raw, Mapping):
        raise RecommendationConfigError(f"profiles.{name}.generators must be a mapping")

    generators: dict[str, ValidatedGeneratorConfig] = {}
    for generator_name, generator_config in generators_raw.items():
        generators[generator_name] = _validate_generator(name, generator_name, generator_config)

    mixing_order = _validate_mixing_order(name, profile_config, generators)
    _validate_scoring(name, profile_config, generators)
    _validate_soft_caps(name, profile_config, generators)

    return ValidatedProfileConfig(
        name=name,
        batch_size=batch_size,
        overfetch_factor=float(overfetch_factor),
        generators=generators,
        mixing_order=tuple(mixing_order),
        raw=profile_config,
    )


def _validate_generator(
    profile_name: str, generator_name: Any, generator_config: Any
) -> ValidatedGeneratorConfig:
    """Validate generator-specific fields without normalizing execution config."""
    if not isinstance(generator_name, str) or not generator_name:
        raise RecommendationConfigError(f"profiles.{profile_name}.generators keys must be strings")
    if generator_name not in ALLOWED_GENERATORS:
        raise RecommendationConfigError(
            f"profiles.{profile_name}.generators.{generator_name} is unknown"
        )
    if not isinstance(generator_config, Mapping):
        raise RecommendationConfigError(
            f"profiles.{profile_name}.generators.{generator_name} must be a mapping"
        )

    enabled = generator_config.get("enabled", True)
    if not isinstance(enabled, bool | int | str):
        raise RecommendationConfigError(
            f"profiles.{profile_name}.generators.{generator_name}.enabled is invalid"
        )

    for key in _RATIO_KEYS:
        if key in generator_config:
            _require_non_negative_number(
                f"profiles.{profile_name}.generators.{generator_name}.{key}", generator_config[key]
            )
    for key in _LIMIT_KEYS:
        if key in generator_config:
            _require_non_negative_number(
                f"profiles.{profile_name}.generators.{generator_name}.{key}", generator_config[key]
            )

    return ValidatedGeneratorConfig(
        name=generator_name,
        enabled=bool(enabled),
        gather_ratio=float(generator_config.get("gather_ratio") or 0.0),
        mix_ratio=float(generator_config.get("mix_ratio") or 0.0),
        raw=generator_config,
    )


def _validate_mixing_order(
    profile_name: str, profile_config: Mapping[str, Any], generators: Mapping[str, Any]
) -> tuple[str, ...]:
    """Validate configured layer order against the current profile generators."""
    mixing = profile_config.get("mixing", {})
    order = mixing.get("order") if isinstance(mixing, Mapping) else None
    if order is None:
        return tuple(generators.keys())
    if not isinstance(order, Sequence) or isinstance(order, str):
        raise RecommendationConfigError(f"profiles.{profile_name}.mixing.order must be a list")
    normalized: list[str] = []
    for item in order:
        if not isinstance(item, str):
            raise RecommendationConfigError(
                f"profiles.{profile_name}.mixing.order must contain strings"
            )
        if item not in generators:
            raise RecommendationConfigError(
                f"profiles.{profile_name}.mixing.order references missing {item}"
            )
        normalized.append(item)
    return tuple(normalized)


def _validate_scoring(
    profile_name: str, profile_config: Mapping[str, Any], generators: Mapping[str, Any]
) -> None:
    """Validate scoring weights while leaving existing scoring execution untouched."""
    scoring = profile_config.get("scoring", {})
    if not isinstance(scoring, Mapping):
        raise RecommendationConfigError(f"profiles.{profile_name}.scoring must be a mapping")
    weights = scoring.get("weights", {})
    if weights is not None:
        if not isinstance(weights, Mapping):
            raise RecommendationConfigError(
                f"profiles.{profile_name}.scoring.weights must be a mapping"
            )
        for key, value in weights.items():
            _require_non_negative_number(f"profiles.{profile_name}.scoring.weights.{key}", value)
    layer_weights = scoring.get("layer_weights", {})
    if layer_weights is not None:
        if not isinstance(layer_weights, Mapping):
            raise RecommendationConfigError(
                f"profiles.{profile_name}.scoring.layer_weights must be a mapping"
            )
        for key, value in layer_weights.items():
            if key not in ALLOWED_GENERATORS:
                raise RecommendationConfigError(
                    f"profiles.{profile_name}.scoring.layer_weights.{key} is unknown"
                )
            _require_number(f"profiles.{profile_name}.scoring.layer_weights.{key}", value)
    if "freshness_half_life_days" in scoring:
        _require_non_negative_number(
            f"profiles.{profile_name}.scoring.freshness_half_life_days",
            scoring["freshness_half_life_days"],
        )
    popularity = scoring.get("popularity", {})
    if popularity is not None:
        if not isinstance(popularity, Mapping):
            raise RecommendationConfigError(
                f"profiles.{profile_name}.scoring.popularity must be a mapping"
            )
        for key, value in popularity.items():
            _require_non_negative_number(f"profiles.{profile_name}.scoring.popularity.{key}", value)


def _validate_soft_caps(
    profile_name: str, profile_config: Mapping[str, Any], generators: Mapping[str, Any]
) -> None:
    """Validate optional soft caps against configured layer names."""
    soft_caps = profile_config.get("soft_caps", {})
    if soft_caps is None:
        return
    if not isinstance(soft_caps, Mapping):
        raise RecommendationConfigError(f"profiles.{profile_name}.soft_caps must be a mapping")
    for bucket in ("min", "max"):
        values = soft_caps.get(bucket, {})
        if values is None:
            continue
        if not isinstance(values, Mapping):
            raise RecommendationConfigError(
                f"profiles.{profile_name}.soft_caps.{bucket} must be a mapping"
            )
        for layer, value in values.items():
            if layer not in generators:
                raise RecommendationConfigError(
                    f"profiles.{profile_name}.soft_caps.{bucket}.{layer} "
                    "references missing generator"
                )
            if not isinstance(value, int) or value < 0:
                raise RecommendationConfigError(
                    f"profiles.{profile_name}.soft_caps.{bucket}.{layer} must be an integer >= 0"
                )


def _require_non_negative_number(path: str, value: Any) -> None:
    """Require a non-negative numeric value and include the config path on errors."""
    _require_number(path, value)
    if float(value) < 0:
        raise RecommendationConfigError(f"{path} must be >= 0")


def _require_number(path: str, value: Any) -> None:
    """Reject non-numeric or bool values without changing accepted defaults."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RecommendationConfigError(f"{path} must be numeric")


# Validate checked-in defaults at import time without changing runtime semantics.
VALIDATED_RECOMMENDATION_CONFIG = validate_recommendation_config(RECOMMENDATION_PIPELINE)
