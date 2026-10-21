"""Characterize recommendation configuration validation and compatibility exports."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from recommendations.config import (  # noqa: E402
    ALLOWED_GENERATORS,
    RECOMMENDATION_PIPELINE,
    RecommendationConfigError,
    clone_recommendation_config,
    validate_recommendation_config,
)


def test_default_config_validation_passes_and_preserves_current_values() -> None:
    """The checked-in pipeline should validate without changing current defaults."""
    validated = validate_recommendation_config(RECOMMENDATION_PIPELINE)

    assert validated.default_profile == "home"
    assert set(validated.profiles) >= {"home", "guest_home", "upnext", "guest_upnext"}
    assert validated.profiles["home"].batch_size == 48
    assert validated.profiles["home"].generators["exploit"].mix_ratio == 0.5


def test_legacy_server_config_import_compatibility_remains() -> None:
    """Existing imports from server_config must remain valid after ownership moves."""
    from server_config import BATCH_SIZE as legacy_batch_size  # noqa: PLC0415
    from server_config import RECOMMENDATION_PIPELINE as legacy_pipeline  # noqa: PLC0415

    assert legacy_pipeline == RECOMMENDATION_PIPELINE
    assert legacy_batch_size == RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]


def test_clone_recommendation_config_does_not_mutate_default_config() -> None:
    """Config clones protect validation/edit tests from mutating runtime defaults."""
    cloned = clone_recommendation_config()
    cloned["profiles"]["home"]["batch_size"] = 1

    assert RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"] == 48


def test_unknown_default_profile_is_rejected() -> None:
    """Validation names the missing default profile path instead of failing later."""
    config = {
        "default_profile": "missing",
        "profiles": {"home": {"batch_size": 48, "generators": {}}},
    }

    with pytest.raises(RecommendationConfigError, match="default_profile.*missing"):
        validate_recommendation_config(config)


def test_unknown_mixing_order_generator_is_rejected() -> None:
    """Mixing order must reference generators configured in the same profile."""
    config = {
        "default_profile": "home",
        "profiles": {
            "home": {
                "batch_size": 10,
                "generators": {"random": {"enabled": True, "mix_ratio": 1.0}},
                "mixing": {"order": ["random", "missing"]},
            }
        },
    }

    with pytest.raises(RecommendationConfigError, match=r"mixing\.order.*missing"):
        validate_recommendation_config(config)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda cfg: cfg["profiles"]["home"].update({"batch_size": -1}), "batch_size"),
        (
            lambda cfg: cfg["profiles"]["home"]["generators"]["random"].update(
                {"pool_size": -1}
            ),
            "pool_size",
        ),
        (
            lambda cfg: cfg["profiles"]["home"]["generators"]["random"].update(
                {"max_per_author": -1}
            ),
            "max_per_author",
        ),
    ],
)
def test_negative_numeric_limits_are_rejected(mutator, expected: str) -> None:
    """Negative limits are rejected at validation instead of changing runtime behavior."""
    config = deepcopy(RECOMMENDATION_PIPELINE)
    mutator(config)

    with pytest.raises(RecommendationConfigError, match=expected):
        validate_recommendation_config(config)


@pytest.mark.parametrize(
    ("key", "value"),
    [("gather_ratio", -0.1), ("mix_ratio", -0.1)],
)
def test_bad_ratios_are_rejected(key: str, value: float) -> None:
    """Configured gather/mix ratios must remain numeric and non-negative."""
    config = deepcopy(RECOMMENDATION_PIPELINE)
    config["profiles"]["home"]["generators"]["random"][key] = value

    with pytest.raises(RecommendationConfigError, match=key):
        validate_recommendation_config(config)


def test_unknown_generator_names_are_rejected() -> None:
    """Only the current documented generator names are accepted by validation."""
    assert ALLOWED_GENERATORS == {"random", "popular", "explore", "exploit", "fresh"}
    config = deepcopy(RECOMMENDATION_PIPELINE)
    config["profiles"]["home"]["generators"]["mystery"] = {"enabled": True}

    with pytest.raises(RecommendationConfigError, match="mystery"):
        validate_recommendation_config(config)
