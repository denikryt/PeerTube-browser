"""Check that urllib never follows a redirect away from the canonical video resource."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.request import build_opener

from engine.server.api.services import peertube_video_detail as detail_service

def test_redirecting_primary_video_never_fetches_followup_resource():
    """Exercise urllib itself: same-origin 302 to 404 must leave original 302."""
    paths: list[str] = []

    class RedirectingHandler(BaseHTTPRequestHandler):
        """Return a redirect to an unrelated absent channel resource."""

        def do_GET(self):
            """Record actual network requests and serve a 302 then optional 404."""
            paths.append(self.path)
            if self.path.startswith("/api/v1/videos/"):
                self.send_response(302)
                self.send_header("Location", "/api/v1/video-channels/missing")
            else:
                self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            """Avoid polluting the test log with local HTTP server diagnostics."""
            pass

    server = HTTPServer(("127.0.0.1", 0), RedirectingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = build_opener(detail_service._NoRedirectHandler())
        status, payload = detail_service._request_json(
            opener, f"http://127.0.0.1:{server.server_port}/api/v1/videos/uuid-1"
        )
        assert (status, payload) == (302, None)
        assert paths == ["/api/v1/videos/uuid-1"]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
