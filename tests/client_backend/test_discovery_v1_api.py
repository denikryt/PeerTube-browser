"""Discovery API v1 Client backend contract tests."""
from __future__ import annotations

import urllib.parse

from repositories.users import UsersRepository


def _row(video_id: str = "v1") -> dict[str, object]:
    return {
        "video_id": video_id,
        "video_uuid": f"uuid-{video_id}",
        "instance_domain": "example.org",
        "title": f"Video {video_id}",
    }


def test_v1_recommendations_get_uses_local_likes(client_db, start_json_engine, start_client_backend) -> None:
    repo = UsersRepository(client_db)
    repo.record_like(
        "u1",
        {"video_id": "liked", "video_uuid": "uuid-liked", "instance_domain": "example.org"},
        100,
    )
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda record: (
                200,
                {"rows": [_row("rec1"), _row("rec2"), _row("rec3")]},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=2&user_id=u1")

    assert response.status_code == 200
    body = response.json()
    assert [row["video_id"] for row in body["items"]] == ["rec1", "rec2", "rec3"]
    assert body["pagination"]["limit"] == 2
    assert body["pagination"]["has_more"] is False
    assert body["meta"] == {"source": "recommendations", "fallback": False, "filters": {"language": None, "category": None, "tag": None, "instance": None}}
    assert fake_engine.requests[0]["method"] == "POST"
    assert fake_engine.requests[0]["body"]["likes"] == [
        {"uuid": "uuid-liked", "host": "example.org"}
    ]


def test_v1_recommendations_limits_local_likes_to_engine_contract(client_db, start_json_engine, start_client_backend) -> None:
    repo = UsersRepository(client_db)
    for index in range(12):
        repo.record_like(
            "u1",
            {
                "video_id": f"liked-{index}",
                "video_uuid": f"uuid-liked-{index}",
                "instance_domain": "example.org",
            },
            100,
        )
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda _record: (
                200,
                {"rows": [_row("rec1")]},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=1&user_id=u1")

    assert response.status_code == 200
    assert len(fake_engine.requests[0]["body"]["likes"]) == 5


def test_v1_recommendations_without_likes_returns_guest_envelope(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine(
        {("POST", "/recommendations"): lambda _record: (200, {"rows": [_row("guest")]})}
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=1&user_id=new")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["video_id"] == "guest"
    assert body["meta"] == {
        "source": "recommendations",
        "fallback": True,
        "fallback_reason": "guest_profile",
        "filters": {"language": None, "category": None, "tag": None, "instance": None},
    }


def test_v1_video_requires_host(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine({("GET", "/api/video"): lambda _record: (200, {})})
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1")

    assert response.status_code == 400
    assert response.json() == {"error": "Missing host", "code": "V1_DISCOVERY_MISSING_HOST"}
    assert fake_engine.requests == []


def test_v1_video_fetches_engine_metadata(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine(
        {
            ("GET", "/api/video"): lambda record: (
                200,
                {
                    "video_id": "v1",
                    "video_uuid": "uuid-v1",
                    "instance_domain": "example.org",
                    "title": "Video",
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1?host=example.org")

    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == "v1"
    assert body["video_uuid"] == "uuid-v1"
    assert body["instance_domain"] == "example.org"
    assert fake_engine.requests[0]["full_path"] == "/api/video?id=v1&host=example.org"


def test_v1_similar_uses_envelope_and_route_bound_cursor(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine(
        {
            ("GET", "/videos/v1/similar"): lambda _record: (
                200,
                {"rows": [_row("s1"), _row("s2"), _row("s3")]},
            ),
            ("GET", "/internal/discovery/fresh"): lambda _record: (200, {"rows": [_row("f1")]}),
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    first = client.get("/api/v1/videos/v1/similar?host=example.org&limit=2")
    assert first.status_code == 200
    body = first.json()
    assert [row["video_id"] for row in body["items"]] == ["s1", "s2"]
    cursor = body["pagination"]["next_cursor"]
    assert isinstance(cursor, str)

    bad = client.get(f"/api/v1/discovery/fresh?cursor={urllib.parse.quote(cursor)}")
    assert bad.status_code == 400
    assert bad.json()["code"] == "V1_DISCOVERY_BAD_REQUEST"


def test_v1_unknown_query_does_not_reach_engine(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine({("GET", "/internal/discovery/fresh"): lambda _record: (200, {})})
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/fresh?unknown=1")

    assert response.status_code == 400
    assert response.json()["code"] == "V1_DISCOVERY_BAD_REQUEST"
    assert fake_engine.requests == []


def test_v1_recommendations_normalizes_thumbnail_from_relative_preview_path(start_json_engine, start_client_backend) -> None:
    """Recommendation rows expose a browser-ready thumbnail_url fallback."""
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda _record: (
                200,
                {
                    "rows": [
                        {
                            "video_id": "rec-preview",
                            "video_uuid": "uuid-rec-preview",
                            "instance_domain": "video.blast-info.fr",
                            "thumbnail_url": None,
                            "preview_path": "/lazy-static/previews/rec-preview.jpg",
                        },
                        _row("extra"),
                    ]
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=1&user_id=image-test")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/rec-preview.jpg"
    assert body["items"][0]["preview_path"] == "/lazy-static/previews/rec-preview.jpg"
    assert body["pagination"]["has_more"] is False


def test_v1_video_detail_normalizes_thumbnail_from_relative_preview_path(start_json_engine, start_client_backend) -> None:
    """Single video metadata responses use the same public thumbnail contract."""
    fake_engine = start_json_engine(
        {
            ("GET", "/api/video"): lambda _record: (
                200,
                {
                    "video_id": "v1",
                    "video_uuid": "uuid-v1",
                    "instance_domain": "video.blast-info.fr",
                    "thumbnail_url": None,
                    "preview_path": "/lazy-static/previews/v1.jpg",
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1?host=video.blast-info.fr")

    assert response.status_code == 200
    body = response.json()
    assert body["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/v1.jpg"
    assert body["preview_path"] == "/lazy-static/previews/v1.jpg"


def test_v1_similar_normalizes_thumbnail_without_changing_pagination(start_json_engine, start_client_backend) -> None:
    """Similar list normalization must not filter rows or alter cursor behavior."""
    fake_engine = start_json_engine(
        {
            ("GET", "/videos/v1/similar"): lambda _record: (
                200,
                {
                    "rows": [
                        {
                            "video_id": "s1",
                            "video_uuid": "uuid-s1",
                            "instance_domain": "video.blast-info.fr",
                            "thumbnail_url": None,
                            "preview_path": "/lazy-static/previews/s1.jpg",
                        },
                        _row("s2"),
                    ]
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1/similar?host=video.blast-info.fr&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/s1.jpg"
    assert body["pagination"]["has_more"] is True
    assert isinstance(body["pagination"]["next_cursor"], str)


def test_v1_fresh_forwards_filters_and_wraps_provider_cursor(start_json_engine, start_client_backend) -> None:
    """Paged Discovery binds the public cursor to source plus raw public filters."""
    def fresh(record):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(record["full_path"]).query)
        if "cursor" not in query:
            return 200, {"rows": [_row("f1")], "pagination": {"limit": 1, "next_cursor": "engine-next", "has_more": True}}
        assert query["cursor"] == ["engine-next"]
        return 200, {"rows": [_row("f2")], "pagination": {"limit": 1, "next_cursor": None, "has_more": False}}

    engine = start_json_engine({("GET", "/internal/discovery/fresh"): fresh})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    first = client.get("/api/v1/discovery/fresh?limit=1&category=Education&language=uk")
    assert first.status_code == 200
    cursor = first.json()["pagination"]["next_cursor"]
    assert cursor
    query = urllib.parse.parse_qs(urllib.parse.urlparse(engine.requests[0]["full_path"]).query)
    assert query["category"] == ["Education"]
    assert query["language"] == ["uk"]

    second = client.get(f"/api/v1/discovery/fresh?limit=1&category=Education&language=uk&cursor={urllib.parse.quote(cursor)}")
    assert second.status_code == 200
    assert [row["video_id"] for row in second.json()["items"]] == ["f2"]

    changed = client.get(f"/api/v1/discovery/fresh?limit=1&category=Music&language=uk&cursor={urllib.parse.quote(cursor)}")
    assert changed.status_code == 400
    assert changed.json()["code"] == "V1_DISCOVERY_BAD_REQUEST"
    wrong_source = client.get(
        f"/api/v1/discovery/popular?limit=1&category=Education&language=uk&cursor={urllib.parse.quote(cursor)}"
    )
    assert wrong_source.status_code == 400
    assert wrong_source.json()["code"] == "V1_DISCOVERY_BAD_REQUEST"


def test_v1_discovery_rejects_old_cursor_and_blank_or_repeated_filter(start_json_engine, start_client_backend) -> None:
    """Old cursor v1 and invalid filter cardinality are rejected before Engine I/O."""
    engine = start_json_engine({("GET", "/internal/discovery/fresh"): lambda _record: (200, {})})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    old = "eyJraW5kIjoiZnJlc2giLCJvZmZzZXQiOjEsInYiOjF9"
    assert client.get(f"/api/v1/discovery/fresh?cursor={old}").status_code == 400
    assert client.get("/api/v1/discovery/fresh?language=").status_code == 400
    assert client.get("/api/v1/discovery/fresh?tag=a&tag=b").status_code == 400
    assert engine.requests == []


def test_v1_random_maps_stale_and_unavailable_provider_errors(start_json_engine, start_client_backend) -> None:
    """Stale continuation and missing provider remain distinct public failures."""
    state = {"mode": "stale"}
    def random_route(_record):
        if state["mode"] == "stale":
            return 400, {"error": "Random cursor belongs to another cache generation", "code": "stale_cursor"}
        return 503, {"error": "Random provider unavailable", "code": "random_provider_unavailable"}
    engine = start_json_engine({("GET", "/internal/discovery/random"): random_route})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    # Manufacture a valid public v2 wrapper around an opaque provider token.
    from services.discovery_v1 import _encode_provider_cursor
    from services.video_filters_v1 import PublicVideoFilters
    cursor = _encode_provider_cursor("random", PublicVideoFilters(), "old-build")
    stale = client.get(f"/api/v1/discovery/random?cursor={urllib.parse.quote(cursor)}")
    assert stale.status_code == 400
    assert stale.json()["code"] == "V1_DISCOVERY_STALE_CURSOR"
    state["mode"] = "unavailable"
    unavailable = client.get("/api/v1/discovery/random")
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "V1_DISCOVERY_PROVIDER_UNAVAILABLE"


def test_v1_recommendations_are_terminal_and_forward_filters(start_json_engine, start_client_backend) -> None:
    """Recommended is a one-shot finite batch and never accepts a continuation cursor."""
    engine = start_json_engine({("POST", "/recommendations"): lambda record: (200, {"rows": [_row("r1")]})})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    response = client.get("/api/v1/discovery/recommendations?limit=50&category=Education&tag=linux")
    assert response.status_code == 200
    assert response.json()["pagination"] == {"limit": 50, "next_cursor": None, "has_more": False}
    query = urllib.parse.parse_qs(urllib.parse.urlparse(engine.requests[0]["full_path"]).query)
    assert query["category"] == ["Education"]
    assert query["tag"] == ["linux"]
    assert query["limit"] == ["50"]
    assert client.get("/api/v1/discovery/recommendations?cursor=anything").status_code == 400


def test_all_four_discovery_routes_share_public_envelope_shape(start_json_engine, start_client_backend) -> None:
    """Positive: Home modes expose one browser-facing envelope despite different provider internals."""
    engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda _record: (200, {"rows": [_row("rec")]}),
            ("GET", "/internal/discovery/fresh"): lambda _record: (200, {"rows": [_row("fresh")], "pagination": {"limit": 20, "next_cursor": None, "has_more": False}}),
            ("GET", "/internal/discovery/popular"): lambda _record: (200, {"rows": [_row("popular")], "pagination": {"limit": 20, "next_cursor": None, "has_more": False}}),
            ("GET", "/internal/discovery/random"): lambda _record: (200, {"rows": [_row("random")], "pagination": {"limit": 20, "next_cursor": None, "has_more": False}}),
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    for source in ("recommendations", "fresh", "popular", "random"):
        response = client.get(f"/api/v1/discovery/{source}?limit=20")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items", "pagination", "meta"}
        assert set(body["pagination"]) == {"limit", "next_cursor", "has_more"}
        assert body["meta"]["source"] == source
        assert set(body["meta"]["filters"]) == {"language", "category", "tag", "instance"}


def test_public_discovery_rejects_invalid_limits_before_engine_io(start_json_engine, start_client_backend) -> None:
    """Negative: malformed/non-positive limits are rejected at the public authoritative boundary."""
    engine = start_json_engine({("GET", "/internal/discovery/fresh"): lambda _record: (200, {})})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    for value in ("0", "-1", "not-a-number"):
        response = client.get(f"/api/v1/discovery/fresh?limit={value}")
        assert response.status_code == 400
    assert engine.requests == []


def test_home_filters_do_not_extend_similar_public_contract(start_json_engine, start_client_backend) -> None:
    """Positive/negative: Similar remains reachable normally and rejects Home-only filter parameters."""
    fake_engine = start_json_engine(
        {
            ("GET", "/videos/v1/similar"): lambda _record: (
                200,
                {"rows": [_row("s1")]},
            ),
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    normal = client.get("/api/v1/videos/v1/similar?host=example.org&limit=1")
    assert normal.status_code == 200
    before = len(fake_engine.requests)

    filtered = client.get("/api/v1/videos/v1/similar?host=example.org&language=uk")
    assert filtered.status_code == 400
    assert len(fake_engine.requests) == before
