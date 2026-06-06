/**
 * Characterization tests for PeerTube thumbnail URL selection.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { resolvePeerTubeMediaUrl, resolvePreferredThumbnailUrl } from "../src/video-media.js";

test("resolvePeerTubeMediaUrl converts relative PeerTube paths to absolute URLs", () => {
  assert.equal(
    resolvePeerTubeMediaUrl("/lazy-static/thumbnails/demo.jpg", "example.org", "https:"),
    "https://example.org/lazy-static/thumbnails/demo.jpg"
  );
  assert.equal(
    resolvePeerTubeMediaUrl("lazy-static/thumbnails/demo.jpg", "example.org", "https:"),
    "https://example.org/lazy-static/thumbnails/demo.jpg"
  );
});

test("resolvePreferredThumbnailUrl prefers live detail thumbnail paths over stale list URLs", () => {
  assert.equal(
    resolvePreferredThumbnailUrl(
      {
        thumbnailUrl: "https://example.org/lazy-static/thumbnails/stale.jpg",
        thumbnailPath: "/lazy-static/thumbnails/live.jpg",
        previewPath: "/lazy-static/thumbnails/preview.jpg"
      },
      "example.org",
      "https:"
    ),
    "https://example.org/lazy-static/thumbnails/live.jpg"
  );
});

test("resolvePreferredThumbnailUrl falls back to previewPath when thumbnailPath is absent", () => {
  assert.equal(
    resolvePreferredThumbnailUrl(
      {
        thumbnailUrl: "https://example.org/lazy-static/thumbnails/stale.jpg",
        previewPath: "/lazy-static/thumbnails/preview.jpg"
      },
      "example.org",
      "https:"
    ),
    "https://example.org/lazy-static/thumbnails/preview.jpg"
  );
});
