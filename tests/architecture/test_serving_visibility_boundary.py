"""Architecture regressions for one ServingVisibility representation across Engine queries."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[2]
ENGINE_SERVER = ROOT / "engine/server"
if str(ENGINE_SERVER) not in sys.path:
    sys.path.insert(0, str(ENGINE_SERVER))

from data.serving_moderation import ServingVisibility, serving_visibility_from_server


def test_runtime_flags_freeze_once_into_serving_visibility() -> None:
    """Positive: explicit runtime moderation flags become one immutable policy object."""
    server = SimpleNamespace(
        video_error_threshold=7,
        enable_instance_ignore=False,
        enable_channel_blocklist=True,
    )
    assert serving_visibility_from_server(server) == ServingVisibility(
        error_threshold=7,
        apply_instance_filter=False,
        apply_channel_filter=True,
    )


def test_missing_runtime_flags_use_existing_visibility_defaults() -> None:
    """Negative/boundary: absent optional runtime attributes preserve current safe defaults."""
    assert serving_visibility_from_server(SimpleNamespace()) == ServingVisibility(
        error_threshold=None,
        apply_instance_filter=True,
        apply_channel_filter=True,
    )


def test_services_pass_policy_objects_and_data_layer_builds_sql() -> None:
    """Positive/negative: SQL fragments never cross API-service/data-query boundaries."""
    discovery = (ROOT / "engine/server/api/services/discovery_service.py").read_text()
    search = (ROOT / "engine/server/api/services/search_service.py").read_text()
    facets = (ROOT / "engine/server/api/services/video_filter_service.py").read_text()
    video_search = (ROOT / "engine/server/data/video_search.py").read_text()
    video_filters = (ROOT / "engine/server/data/video_filters.py").read_text()

    for service in (discovery, search, facets):
        assert "serving_visibility_from_server" in service
        assert "build_serving_visibility_sql" not in service
    assert "visibility: ServingVisibility" in video_search
    assert "visibility: ServingVisibility" in video_filters
    assert "build_serving_visibility_sql" in video_search
    assert "build_serving_visibility_sql" in video_filters
