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
    assert row["thumbnail_urls"] == ["https://cdn.example/thumb.jpg"]
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
    assert row["thumbnail_urls"] == [
        "https://video.blast-info.fr/static/thumbnails/thumb.jpg"
    ]


def test_explicit_thumbnail_urls_are_normalized_deduped_and_drive_singular_mirror() -> None:
    """Candidate lists are the browser-facing source when Engine supplies them."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "https://stale.example/old.jpg",
            "thumbnail_urls": [
                "/static/thumbnails/large.jpg",
                "https://cdn.example/small.jpg",
                "/static/thumbnails/large.jpg",
                "ftp://cdn.example/bad.jpg",
                "   ",
            ],
            "preview_path": "https://cdn.example/preview.jpg",
        }
    )

    assert row["thumbnail_urls"] == [
        "https://video.blast-info.fr/static/thumbnails/large.jpg",
        "https://cdn.example/small.jpg",
    ]
    assert row["thumbnail_url"] == "https://video.blast-info.fr/static/thumbnails/large.jpg"


def test_thumbnail_candidate_objects_keep_safe_dimensions_and_drive_url_compatibility() -> None:
    """Candidate objects survive the Client boundary while URL mirrors stay compatible."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "https://stale.example/old.jpg",
            "thumbnail_urls": ["https://stale.example/old.jpg"],
            "thumbnail_candidates": [
                {"url": "/static/thumbnails/large.jpg", "width": 1280, "height": 720},
                {"url": "/static/thumbnails/medium.jpg", "width": 850, "height": 480},
                {"url": "/static/thumbnails/unknown.jpg", "width": "850", "height": True},
                {"url": "/static/thumbnails/medium.jpg", "width": 850, "height": 480},
                {"url": "ftp://cdn.example/ignored.jpg", "width": 1, "height": 1},
            ],
        }
    )

    assert row["thumbnail_candidates"] == [
        {
            "url": "https://video.blast-info.fr/static/thumbnails/large.jpg",
            "width": 1280,
            "height": 720,
        },
        {
            "url": "https://video.blast-info.fr/static/thumbnails/medium.jpg",
            "width": 850,
            "height": 480,
        },
        {
            "url": "https://video.blast-info.fr/static/thumbnails/unknown.jpg",
            "width": None,
            "height": None,
        },
    ]
    assert row["thumbnail_urls"] == [candidate["url"] for candidate in row["thumbnail_candidates"]]
    assert row["thumbnail_url"] == row["thumbnail_urls"][0]


def test_explicit_empty_thumbnail_urls_do_not_resurrect_preview_or_singular() -> None:
    """An explicit empty Engine list stays empty and preview is never promoted."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "https://cdn.example/stale.jpg",
            "thumbnail_urls": [],
            "preview_path": "/lazy-static/previews/d66e5234.jpg",
        }
    )

    assert row["thumbnail_urls"] == []
    assert row["thumbnail_url"] is None
    assert row["preview_path"] == "/lazy-static/previews/d66e5234.jpg"


def test_empty_strings_are_ignored_and_source_row_is_not_mutated() -> None:
    """Normalization skips blank values and never mutates the Engine source row."""
    source = {
        "instance_domain": "video.blast-info.fr",
        "thumbnail_url": "   ",
        "preview_path": " lazy-static/previews/fallback.jpg ",
    }

    row = normalize_video_row_for_browser(source)

    assert row["thumbnail_url"] is None
    assert row["thumbnail_urls"] == []
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
    assert row["thumbnail_urls"] == []
    assert resolve_absolute_media_url("/lazy-static/previews/missing-host.jpg", None) is None


def test_instance_domain_scheme_is_normalized_for_relative_thumbnail_paths() -> None:
    """Rows with scheme-bearing instance domains still normalize singular thumbnails."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "https://video.blast-info.fr",
            "thumbnail_url": "/static/thumbnails/a.jpg",
            "preview_path": "/lazy-static/previews/a.jpg",
        }
    )

    assert row["thumbnail_url"] == "https://video.blast-info.fr/static/thumbnails/a.jpg"
    assert row["thumbnail_urls"] == ["https://video.blast-info.fr/static/thumbnails/a.jpg"]


def test_protocol_relative_urls_and_non_http_schemes_are_rejected() -> None:
    """Unsupported absolute-like media URLs remain unsupported by the v1 resolver."""
    for value in (
        "ftp://cdn.example/thumb.jpg",
        "data:image/png,abc",
        "blob:https://cdn.example/id",
        "custom:thumb",
    ):
        assert resolve_absolute_media_url(value, "video.blast-info.fr") is None
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "//cdn.example/thumb.jpg",
            "preview_path": None,
        }
    )

    assert row["thumbnail_url"] is None
    assert row["thumbnail_urls"] == []


def test_thumbnail_urls_absent_keeps_legacy_singular_fallback_without_preview() -> None:
    """Old Engine rows still expose one singular thumbnail, but never preview fallback."""
    row = normalize_video_row_for_browser(
        {
            "instance_domain": "video.blast-info.fr",
            "thumbnail_url": "/static/thumbnails/legacy.jpg",
            "preview_path": "/lazy-static/previews/preview.jpg",
        }
    )

    assert row["thumbnail_urls"] == [
        "https://video.blast-info.fr/static/thumbnails/legacy.jpg"
    ]
    assert row["thumbnail_url"] == row["thumbnail_urls"][0]
