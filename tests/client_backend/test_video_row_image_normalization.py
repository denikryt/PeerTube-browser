"""Client video-row image URL normalization behavior tests."""
from __future__ import annotations

from services.video_rows import normalize_video_row_for_browser, resolve_absolute_media_url


def test_absolute_thumbnail_url_is_preserved_and_wins_over_preview_path() -> None:
    """Browser rows keep an absolute thumbnail as the canonical card image."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "https://cdn.example/thumb.jpg",
            "preview_path": "/lazy-static/previews/preview.jpg",
        }
    )

    assert row["thumbnail_url"] == "https://cdn.example/thumb.jpg"
    assert row["preview_path"] == "/lazy-static/previews/preview.jpg"


def test_relative_thumbnail_url_is_joined_with_instance_domain() -> None:
    """Relative thumbnails become browser-ready absolute URLs."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "static/thumbnails/thumb.jpg",
            "preview_path": "/lazy-static/previews/preview.jpg",
        }
    )

    assert row["thumbnail_url"] == "https://video.blast-info.fr/static/thumbnails/thumb.jpg"


def test_missing_thumbnail_url_falls_back_to_absolute_preview_path() -> None:
    """Absolute preview paths are used only when no thumbnail source exists."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": None,
            "preview_path": "https://cdn.example/preview.jpg",
        }
    )

    assert row["thumbnail_url"] == "https://cdn.example/preview.jpg"


def test_missing_thumbnail_url_falls_back_to_relative_preview_path() -> None:
    """PeerTube relative previews are resolved against the instance domain."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": None,
            "preview_path": "/lazy-static/previews/d66e5234.jpg",
        }
    )

    assert row["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/d66e5234.jpg"
    assert row["preview_path"] == "/lazy-static/previews/d66e5234.jpg"


def test_empty_strings_are_ignored_and_source_row_is_not_mutated() -> None:
    """Normalization skips blank values and never mutates the Engine source row."""
    source = {
        "instance_domain": "video.blast-info.fr",
        "thumbnail_url": "   ",
        "preview_path": " lazy-static/previews/fallback.jpg ",
    }

    row = normalize_video_row_for_browser(source)

    assert row["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/fallback.jpg"
    assert source["thumbnail_url"] == "   "
    assert source["preview_path"] == " lazy-static/previews/fallback.jpg "


def test_relative_paths_without_instance_domain_return_null() -> None:
    """Relative media sources are unsafe without the row instance domain."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "",
            "thumbnail_url": None,
            "preview_path": "/lazy-static/previews/missing-host.jpg",
        }
    )

    assert row["thumbnail_url"] is None
    assert resolve_absolute_media_url("/lazy-static/previews/missing-host.jpg", None) is None


def test_instance_domain_scheme_is_normalized_for_relative_paths() -> None:
    """Rows with scheme-bearing instance domains still produce one https URL."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "https://video.blast-info.fr",
            "thumbnail_url": None,
            "preview_path": "/lazy-static/previews/a.jpg",
        }
    )

    assert row["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/a.jpg"


def test_protocol_relative_urls_and_non_http_schemes_are_rejected() -> None:
    """Unsupported absolute-like media URLs remain unsupported by the v1 resolver."""
    assert resolve_absolute_media_url("ftp://cdn.example/thumb.jpg", "video.blast-info.fr") is None
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "//cdn.example/thumb.jpg",
            "preview_path": None,
        }
    )

    assert row["thumbnail_url"] is None
