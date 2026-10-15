"""End-to-end direct-video ownership, moderation, and PeerTube observation regressions."""

from __future__ import annotations

import json
import sqlite3
from socketserver import BaseRequestHandler, TCPServer
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
import threading
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from types import SimpleNamespace

import pytest

from handlers import video
from services import peertube_video_detail as detail_service
from services.peertube_video_detail import VideoDetailResult
from engine.server.db.bootstrap import bootstrap_engine_runtime_db

ROOT = Path(__file__).resolve().parents[2]


def _db() -> sqlite3.Connection:
    """Create the actual crawler schema plus Engine-owned moderation bootstrap."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "engine/crawler/schema.sql").read_text())
    bootstrap_engine_runtime_db(conn)
    conn.execute(
        "INSERT INTO channels(channel_id,instance_domain,channel_name,display_name,followers_count) "
        "VALUES('c','example.org','slug','DB Channel',23)"
    )
    conn.execute(
        "INSERT INTO instances(host,last_error,last_error_at) VALUES('example.org','offline',123)"
    )
    conn.execute(
        """INSERT INTO videos(video_id,video_uuid,instance_domain,channel_id,
           title,description,views,likes,dislikes,error_count,last_checked_at,invalid_reason)
           VALUES('id-1','uuid-1','example.org','c','Cached title','Cached desc',10,3,1,100,222,NULL)"""
    )
    conn.commit()
    return conn


def _server(conn: sqlite3.Connection, *, instance: bool = True, channel: bool = True) -> SimpleNamespace:
    """Expose the two independent Engine moderation switches and SQLite lock."""
    return SimpleNamespace(
        db=conn, db_lock=threading.RLock(),
        enable_instance_ignore=instance, enable_channel_blocklist=channel,
    )


def _snapshot(conn: sqlite3.Connection) -> tuple[list[tuple], ...]:
    """Capture tables that a direct-video read must never mutate."""
    return tuple(
        [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("videos", "channels", "instances")
    )


@pytest.mark.parametrize("kind", ["available", "not_found", "gone", "unknown"])
def test_detail_result_rejects_contradictory_payloads(kind):
    """Positive: valid tagged result; negative: payload on absence or missing reason."""
    if kind == "available":
        assert VideoDetailResult(kind, detail={}).detail == {}
        with pytest.raises(ValueError):
            VideoDetailResult(kind)
    elif kind == "unknown":
        assert VideoDetailResult(kind, error="unavailable").kind == kind
        with pytest.raises(ValueError):
            VideoDetailResult(kind)
    else:
        assert VideoDetailResult(kind).kind == kind
        with pytest.raises(ValueError):
            VideoDetailResult(kind, detail={})


@pytest.mark.parametrize("reason", ["not_found", "gone", "", "legacy_unknown"])
def test_canonical_invalidity_returns_404_without_network(monkeypatch, reason):
    """Any non-NULL invalidity is excluded before the remote fetch."""
    conn = _db()
    conn.execute("UPDATE videos SET invalid_reason=?", (reason,))
    called = []
    monkeypatch.setattr(video, "fetch_peertube_video_detail", lambda *args: called.append(args))
    result = video.handle_video_request(_server(conn), {"id": ["uuid-1"]})
    assert result.status == 404 and result.payload == {"error": "Video not found"}
    assert called == []
    conn.close()


@pytest.mark.parametrize(
    "instance,channel,deny,block,allowed",
    [
        (True, True, True, False, False),
        (True, True, False, True, False),
        (True, False, False, True, True),
        (False, True, True, False, True),
        (False, True, True, True, False),
        (True, False, True, True, False),
        (False, False, True, True, True),
        (True, True, False, False, True),
    ],
)
def test_moderation_flags_apply_before_network(monkeypatch, instance, channel, deny, block, allowed):
    """Blocked rows never cross HTTP; each disabled flag lifts only its own gate."""
    conn = _db()
    if deny:
        conn.execute("INSERT INTO instance_denylist(host,is_active,created_at,updated_at) VALUES('EXAMPLE.ORG',1,1,1)")
    if block:
        conn.execute(
            "INSERT INTO channel_moderation(channel_id,instance_domain,status,created_at,updated_at) "
            "VALUES('c','example.org','blocked',1,1)"
        )
    called: list[tuple[str, str]] = []

    def observe(host, uuid):
        """Return DB fallback after recording the canonical remote identity."""
        called.append((host, uuid))
        return VideoDetailResult("unknown", error="offline")

    monkeypatch.setattr(video, "fetch_peertube_video_detail", observe)
    result = video.handle_video_request(_server(conn, instance=instance, channel=channel), {"id": ["id-1"]})
    assert result.status == (200 if allowed else 404)
    assert called == ([("example.org", "uuid-1")] if allowed else [])
    conn.close()


def test_inactive_denylist_and_allowed_channel_keep_high_error_video_visible(monkeypatch):
    """Inactive moderation and error_count=100 must not conceal a valid row."""
    conn = _db()
    conn.execute("INSERT INTO instance_denylist(host,is_active,created_at,updated_at) VALUES('example.org',0,1,1)")
    conn.execute("INSERT INTO channel_moderation(channel_id,instance_domain,status,created_at,updated_at) VALUES('c','example.org','allowed',1,1)")
    monkeypatch.setattr(video, "fetch_peertube_video_detail", lambda *_: VideoDetailResult("unknown", error="offline"))
    result = video.handle_video_request(_server(conn), {"id": ["uuid-1"], "host": ["example.org"]})
    assert result.status == 200 and result.payload["title"] == "Cached title"
    assert result.payload["views"] == 10
    conn.close()


def test_hostless_collision_cannot_prefer_blocked_candidate(monkeypatch):
    """Moderation must run in the SELECT, not after an arbitrary LIMIT 1 row."""
    conn = _db()
    conn.execute("INSERT INTO instances(host) VALUES('other.example')")
    conn.execute(
        "INSERT INTO channels(channel_id,instance_domain,channel_name) VALUES('other','other.example','slug')"
    )
    conn.execute(
        "INSERT INTO videos(video_id,video_uuid,instance_domain,channel_id,title,last_checked_at) "
        "VALUES('id-1','uuid-allowed','other.example','other','Allowed',1)"
    )
    conn.execute("INSERT INTO instance_denylist(host,is_active,created_at,updated_at) VALUES('example.org',1,1,1)")
    seen = []

    def observe(host, uuid):
        """Record which admitted remote identity was selected."""
        seen.append((host, uuid))
        return VideoDetailResult("unknown", error="offline")

    monkeypatch.setattr(video, "fetch_peertube_video_detail", observe)
    result = video.handle_video_request(_server(conn), {"id": ["id-1"]})
    assert result.status == 200 and result.payload["instance_domain"] == "other.example"
    assert seen == [("other.example", "uuid-allowed")]
    conn.close()


@pytest.mark.parametrize("result", [
    VideoDetailResult("unknown", error="timeout"),
    VideoDetailResult("available", detail={
        "title": "Live title", "views": 0, "likes": 0, "dislikes": 0,
        "channel_display": "Live channel", "channel_followers": 0,
    }),
])
def test_live_overlay_and_cached_fallback_leave_three_tables_unchanged(monkeypatch, result):
    """No success/failure of request-time detail can write canonical input tables."""
    conn = _db()
    before = _snapshot(conn)
    monkeypatch.setattr(video, "fetch_peertube_video_detail", lambda *_: result)
    response = video.handle_video_request(_server(conn), {"id": ["uuid-1"]})
    assert response.status == 200
    assert _snapshot(conn) == before
    if result.kind == "available":
        assert response.payload["title"] == "Live title"
        assert response.payload["views"] == 0
        assert response.payload["likes"] == 0
        assert response.payload["subscribersCount"] == 0
    else:
        assert response.payload["views"] == 10
        assert response.payload["channelName"] == "DB Channel"
    conn.close()


@pytest.mark.parametrize("kind", ["not_found", "gone"])
def test_request_only_absence_keeps_canonical_availability(monkeypatch, kind):
    """Primary absence returns 404 but publication remains the Updater's job."""
    conn = _db()
    before = _snapshot(conn)
    monkeypatch.setattr(video, "fetch_peertube_video_detail", lambda *_: VideoDetailResult(kind))
    response = video.handle_video_request(_server(conn), {"id": ["id-1"]})
    assert response.status == 404 and _snapshot(conn) == before
    conn.close()


@pytest.mark.parametrize("status,expected", [
    (200, "available"), (404, "not_found"), (410, "gone"),
    (301, "unknown"), (302, "unknown"), (303, "unknown"),
    (307, "unknown"), (308, "unknown"),
    (403, "unknown"), (429, "unknown"), (503, "unknown"),
])
def test_primary_http_status_is_classified_at_original_resource(monkeypatch, status, expected):
    """A redirect is unknown rather than a 404 inferred from another endpoint."""
    requests = []

    def request(_opener, url):
        """Only one primary request should occur when the status is not 200."""
        requests.append(url)
        return status, {"uuid": "uuid-1", "name": "Fresh"} if status == 200 else None

    monkeypatch.setattr(detail_service, "_request_json", request)
    result = detail_service.fetch_peertube_video_detail("example.org", "uuid-1")
    assert result.kind == expected
    assert requests == ["https://example.org/api/v1/videos/uuid-1"]


@pytest.mark.parametrize("payload", [[], None, "garbage", {}, {"uuid": "other"}, {"uuid": None}])
def test_invalid_detail_wire_identity_is_unknown(monkeypatch, payload):
    """Untrusted JSON must not turn an invalid or mismatched UUID into availability."""
    monkeypatch.setattr(detail_service, "_request_json", lambda *_: (200, payload))
    assert detail_service.fetch_peertube_video_detail("example.org", "uuid-1").kind == "unknown"


def test_channel_failure_is_only_lost_enrichment(monkeypatch):
    """An embedded valid video survives a 404 from optional channel enrichment."""
    urls: list[str] = []

    def request(_opener, url):
        """Return valid primary identity then an unrelated absent channel resource."""
        urls.append(url)
        if "/video-channels/" in url:
            return 404, None
        return 200, {"uuid": "uuid-1", "name": "Fresh", "channel": {"name": "slug"}}

    monkeypatch.setattr(detail_service, "_request_json", request)
    result = detail_service.fetch_peertube_video_detail("example.org", "uuid-1")
    assert result.kind == "available" and result.detail["title"] == "Fresh"
    assert len(urls) == 2


def test_complete_embedded_channel_avoids_second_request(monkeypatch):
    """Already complete channel metadata must not trigger an unnecessary API request."""
    urls: list[str] = []

    def request(_opener, url):
        """Supply complete nested channel and count zero without second fetch."""
        urls.append(url)
        return 200, {
            "uuid": "uuid-1", "views": 0, "likes": 0,
            "account": "not-an-object",
            "channel": {"name": "slug", "displayName": "Display", "followersCount": 0},
        }

    monkeypatch.setattr(detail_service, "_request_json", request)
    result = detail_service.fetch_peertube_video_detail("example.org", "uuid-1")
    assert result.kind == "available"
    assert result.detail["channel_followers"] == 0
    assert len(urls) == 1


def test_invalid_stored_origin_or_uuid_skips_network(monkeypatch):
    """No URL constructed from a malformed DB authority or missing UUID."""
    called = []
    monkeypatch.setattr(detail_service, "build_opener", lambda *_: called.append(1))
    for host, uuid in [("example.org/path", "uuid-1"), ("user@host", "uuid-1"), ("example.org", "")]:
        assert detail_service.fetch_peertube_video_detail(host, uuid).kind == "unknown"
    assert called == []


def test_concurrent_requests_do_not_order_or_persist_remote_overlays(monkeypatch):
    """Two read-only requests may wait on HTTP concurrently without DB write races."""
    conn = _db()
    before = _snapshot(conn)
    server = _server(conn)
    overlap = Barrier(2)

    def observe(_host: str, _uuid: str) -> VideoDetailResult:
        """Require both requests to leave the DB lock before either returns."""
        overlap.wait(timeout=5)
        return VideoDetailResult("available", detail={"title": "Fresh", "views": 0})

    monkeypatch.setattr(video, "fetch_peertube_video_detail", observe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: video.handle_video_request(server, {"id": ["id-1"]}), range(2)))

    assert [result.status for result in responses] == [200, 200]
    assert [result.payload["views"] for result in responses] == [0, 0]
    assert _snapshot(conn) == before
    conn.close()


def test_publisher_commit_between_lookup_and_network_remains_authoritative(monkeypatch, tmp_path):
    """An in-flight observation cannot resurrect a row invalidated by publication."""
    memory_db = _db()
    db_path = tmp_path / "canonical.db"
    serving_conn = sqlite3.connect(db_path, check_same_thread=False)
    serving_conn.row_factory = sqlite3.Row
    memory_db.backup(serving_conn)
    memory_db.close()
    publisher_conn = sqlite3.connect(db_path)
    try:
        server = _server(serving_conn)
        observed = []

        def publish_during_fetch(host: str, uuid: str) -> VideoDetailResult:
            """Commit an authoritative tombstone after the request reads its row."""
            observed.append((host, uuid))
            publisher_conn.execute(
                "UPDATE videos SET invalid_reason='gone', invalid_at=456 WHERE video_id='id-1'"
            )
            publisher_conn.commit()
            return VideoDetailResult("available", detail={"title": "Live while publishing"})

        monkeypatch.setattr(video, "fetch_peertube_video_detail", publish_during_fetch)
        in_flight = video.handle_video_request(server, {"id": ["id-1"]})
        assert in_flight.status == 200 and in_flight.payload["title"] == "Live while publishing"
        assert observed == [("example.org", "uuid-1")]
        assert tuple(publisher_conn.execute(
            "SELECT invalid_reason,invalid_at FROM videos WHERE video_id='id-1'"
        ).fetchone()) == ("gone", 456)

        # The second lookup sees committed canonical state, not the prior overlay.
        observed.clear()
        next_request = video.handle_video_request(server, {"id": ["id-1"]})
        assert next_request.status == 404 and observed == []
    finally:
        publisher_conn.close()
        serving_conn.close()


@pytest.mark.parametrize("body", [b"not json", b"{", b"[1,2]", b"\xff"])
def test_invalid_wire_body_returns_unknown_without_remote_fields(monkeypatch, body):
    """Malformed text, incomplete objects, arrays, and decoding errors fail closed."""
    class Response:
        """One success-status HTTP response exposing untrusted bytes."""
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return body

    class FakeOpener:
        """Assert that the service retains the original TLS URL and timeout."""
        def open(self, request, timeout):
            assert request.full_url == "https://example.org/api/v1/videos/uuid-1"
            assert request.get_header("Accept") == "application/json"
            assert timeout == 8
            return Response()

    monkeypatch.setattr(detail_service, "build_opener", lambda *_args: FakeOpener())
    result = detail_service.fetch_peertube_video_detail("example.org", "uuid-1")
    assert result.kind == "unknown" and result.detail is None


@pytest.mark.parametrize("failure", ["incomplete_body", "bad_status_line"])
@pytest.mark.parametrize("resource", ["primary", "channel"])
def test_http_protocol_failure_preserves_cached_or_live_video(monkeypatch, resource, failure):
    """Actual truncated/malformed HTTP responses must never cause a video 500."""
    requested: list[str] = []

    class BrokenResponseHandler(BaseRequestHandler):
        """Serve wire-level HTTP framing faults without an internal route adapter."""

        def handle(self):
            """Receive the path, then send either a complete or malformed reply."""
            request_line = self.request.recv(4096).split(b"\r\n", 1)[0]
            path = request_line.split(b" ", 2)[1].decode("ascii")
            requested.append(path)
            is_video = path.startswith("/api/v1/videos/")
            if resource == "channel" and is_video:
                body = json.dumps({
                    "uuid": "uuid-1", "name": "Fresh title", "views": 12,
                    "channel": {"name": "slug"},
                }).encode("utf-8")
                self.request.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
            elif failure == "incomplete_body":
                body = b'{"uuid": "uuid-1"'
                self.request.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body) + 100}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
            else:
                # An invalid status line makes http.client raise BadStatusLine.
                self.request.sendall(b"BROKEN_RESPONSE\r\n\r\n")

    http_server = TCPServer(("127.0.0.1", 0), BrokenResponseHandler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()

    class LocalTransportOpener:
        """Keep production stored-identity HTTPS URL formation but use local HTTP."""

        def open(self, request, timeout):
            """Forward to the test server, retaining timeout and redirect policy."""
            assert request.full_url.startswith("https://example.org/api/v1/")
            local = Request(
                f"http://127.0.0.1:{http_server.server_address[1]}{urlsplit(request.full_url).path}",
                headers={"Accept": "application/json"},
            )
            return build_opener(detail_service._NoRedirectHandler()).open(local, timeout=timeout)

    conn = _db()
    try:
        before = _snapshot(conn)
        monkeypatch.setattr(detail_service, "build_opener", lambda *_args: LocalTransportOpener())
        result = video.handle_video_request(_server(conn), {"id": ["uuid-1"]})
        assert result.status == 200
        if resource == "primary":
            assert result.payload["title"] == "Cached title"
            assert result.payload["views"] == 10
            assert requested == ["/api/v1/videos/uuid-1"]
        else:
            assert result.payload["title"] == "Fresh title"
            assert result.payload["views"] == 12
            assert result.payload["channelName"] == "DB Channel"
            assert requested == ["/api/v1/videos/uuid-1", "/api/v1/video-channels/slug"]
        assert _snapshot(conn) == before
    finally:
        conn.close()
        http_server.shutdown()
        thread.join(timeout=5)
        http_server.server_close()


@pytest.mark.parametrize("malformed", [
    pytest.param("²", id="unicode-nonconvertible"),
    pytest.param("9" * 10000, id="excessive-number-length"),
])
def test_nonconvertible_optional_counts_use_cached_values(monkeypatch, malformed):
    """Malformed optional numeric metadata cannot invalidate an identified video."""
    conn = _db()
    before = _snapshot(conn)

    def request(_opener, _url):
        """Return a valid video identity with unusable and usable optional counts."""
        return 200, {
            "uuid": "uuid-1", "name": "Fresh title", "views": malformed,
            "likes": malformed, "likesCount": 7, "dislikes": 0,
            "channel": {"name": "slug", "displayName": "Fresh channel", "followersCount": 3},
        }

    monkeypatch.setattr(detail_service, "_request_json", request)
    try:
        result = video.handle_video_request(_server(conn), {"id": ["uuid-1"]})
        assert result.status == 200
        assert result.payload["title"] == "Fresh title"
        assert result.payload["views"] == 10  # Invalid counter -> persisted value.
        assert result.payload["likes"] == 7  # A later valid alternative remains usable.
        assert result.payload["dislikes"] == 0  # Valid zero remains explicit.
        assert _snapshot(conn) == before
    finally:
        conn.close()
