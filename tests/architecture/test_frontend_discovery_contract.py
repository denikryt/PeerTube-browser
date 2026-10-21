"""Static frontend ownership regressions runnable without Node dependencies."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client/frontend/src"


def _text(relative: str) -> str:
    """Read one frontend source file for boundary assertions."""
    return (FRONTEND / relative).read_text()


def test_frontend_discovery_search_and_facets_use_client_public_routes_only() -> None:
    """Positive/negative: browser data helpers target /api/v1 and never Engine internals."""
    sources = [_text("data/discovery.ts"), _text("data/search.ts"), _text("data/video-facets.ts")]
    joined = "\n".join(sources)
    for path in (
        "/api/v1/discovery/",
        "/api/v1/search/videos",
        "/api/v1/search/channels",
        "/api/v1/video-facets",
    ):
        assert path in joined
    assert "/internal/" not in joined


def test_video_detail_similar_transport_cannot_fall_back_to_discovery() -> None:
    """Positive/negative: Similar stays video-scoped and a missing video id is rejected."""
    source = _text("data/videos.ts")
    assert "/api/v1/videos/${encodeURIComponent(videoId)}/similar" in source
    assert "Similar video id is required" in source
    assert "/api/v1/discovery/" not in source


def test_home_cache_observer_and_scroll_ownership_are_explicit() -> None:
    """Positive/negative: Home owns viewport lifecycle but not provider cursor mutation."""
    home = _text("views/HomeView.vue")
    app = _text("App.vue")
    router = _text("router/index.ts")
    assert "new IntersectionObserver" in home
    assert "onActivated" in home and "onDeactivated" in home and "onUnmounted" in home
    assert "disconnectObserver()" in home
    assert "suspend()" not in home
    assert "void loadMore()" in home
    assert "state.nextCursor =" not in home
    assert "fetchDiscoveryPayload" not in home
    assert "<KeepAlive>" in app and "route.name === 'home'" in app
    assert "savedPosition ?? { top: 0 }" in router



def test_home_and_search_share_one_filter_controls_component() -> None:
    """Positive/negative: shared filter UX has one owner while pages keep URL ownership."""
    home = _text("views/HomeView.vue")
    search = _text("views/SearchView.vue")
    controls = _text("components/VideoFilterControls.vue")

    assert "<VideoFilterControls" in home and '@change="setFilters"' in home
    assert "<VideoFilterControls" in search and '@change="setFilters"' in search
    assert "fetchVideoFacetsPayload" in controls
    assert "!facets?.languages.some" in controls
    assert "!facets?.categories.some" in controls
    assert "fetchVideoFacetsPayload" not in home
    assert "fetchVideoFacetsPayload" not in search
    assert "facetsLoading" not in home and "facetsLoading" not in search

def test_finite_recommended_compatibility_is_narrow_and_search_channels_stay_unfiltered() -> None:
    """Positive/negative: finite Recommended remains local while channel search has no video-filter path."""
    feed = _text("composables/useFeed.ts")
    search = _text("data/search.ts")
    assert feed.count("TEMP-DISCOVERY-RECOMMENDATIONS:") == 2
    assert "recommendationVisibleCount" in feed
    assert "state.mode === \"recommendations\"" in feed
    assert 'buildSearchUrl("/api/v1/search/channels", options, false)' in search
    assert 'buildSearchUrl("/api/v1/search/videos", options, true)' in search


def test_cards_render_optional_metadata_without_unknown_placeholders() -> None:
    """Positive/negative: canonical metadata is shown only when actually present."""
    card = _text("components/VideoCard.vue")
    assert "instanceLabel" in card and "languageLabel" in card and "categoryLabel" in card
    assert 'normalized !== "_unknown"' in card
    assert "Unknown language" not in card
    assert "Unknown category" not in card


def test_finite_recommended_temp_markers_match_planned_removal_contract() -> None:
    """Positive/negative: all temporary bridges are searchable and no wider redesign exists."""
    engine = (ROOT / "engine/server/api/services/recommendation_service.py").read_text()
    client = (ROOT / "client/backend/services/discovery_v1.py").read_text()
    feed = _text("composables/useFeed.ts")
    assert (
        "# TEMP-DISCOVERY-RECOMMENDATIONS: final-filter the finite legacy recommendation batch here; "
        "remove when recommendations have a native filtered paged/snapshot provider that can refill beyond the legacy batch."
    ) in engine
    assert (
        "# TEMP-DISCOVERY-RECOMMENDATIONS: adapt the finite legacy Engine batch to terminal Discovery pagination; "
        "remove when Engine recommendations expose a native continuation contract."
    ) in client
    assert (
        "// TEMP-DISCOVERY-RECOMMENDATIONS: buffer the one-shot finite recommendation batch for local paging; "
        "remove when Recommended exposes a native continuation contract."
    ) in feed
    assert (
        "// TEMP-DISCOVERY-RECOMMENDATIONS: reveal the one-shot finite recommendation batch locally; "
        "remove when Recommended exposes a native continuation contract."
    ) in feed
    assert not (ROOT / "engine/server/api/recommendations/context.py").exists()
