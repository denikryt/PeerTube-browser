/** Regression tests for PeerTube thumbnail candidate normalization. */

import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveLegacyThumbnailCompatibility,
  resolvePeerTubeMediaUrl,
  resolveThumbnailCandidates
} from "../src/video-media.js";

test("resolvePeerTubeMediaUrl converts relative paths but rejects unsupported explicit schemes", () => {
  assert.equal(
    resolvePeerTubeMediaUrl("/lazy-static/thumbnails/demo.jpg", "example.org", "https:"),
    "https://example.org/lazy-static/thumbnails/demo.jpg"
  );
  assert.equal(
    resolvePeerTubeMediaUrl("lazy-static/thumbnails/demo.jpg", "example.org", "https:"),
    "https://example.org/lazy-static/thumbnails/demo.jpg"
  );
  for (const value of ["ftp://example.org/a.jpg", "data:image/png,abc", "blob:https://x/y", "custom:thing"]) {
    assert.equal(resolvePeerTubeMediaUrl(value, "example.org", "https:"), null);
  }
});

test("resolveThumbnailCandidates distinguishes unavailable source from authoritative empty array", () => {
  assert.equal(resolveThumbnailCandidates(undefined, "example.org", "https:"), null);
  assert.equal(resolveThumbnailCandidates(null, "example.org", "https:"), null);
  assert.equal(resolveThumbnailCandidates("garbage", "example.org", "https:"), null);
  assert.deepEqual(resolveThumbnailCandidates([], "example.org", "https:"), []);
});

test("resolveThumbnailCandidates preserves every usable URL in larger-to-smaller order", () => {
  assert.deepEqual(
    resolveThumbnailCandidates(
      [
        { fileUrl: "/thumb-small.jpg", width: 280, height: 157 },
        { fileUrl: "/thumb-large.jpg", width: 850, height: 480 },
        { fileUrl: "/thumb-tie.jpg", width: 850, height: 480 },
        { fileUrl: "/thumb-unknown.jpg" }
      ],
      "example.org",
      "https:"
    ),
    [
      { url: "https://example.org/thumb-large.jpg", width: 850, height: 480 },
      { url: "https://example.org/thumb-tie.jpg", width: 850, height: 480 },
      { url: "https://example.org/thumb-small.jpg", width: 280, height: 157 },
      { url: "https://example.org/thumb-unknown.jpg", width: null, height: null }
    ]
  );
});

test("resolveThumbnailCandidates sorts before URL dedup and ignores malformed members", () => {
  assert.deepEqual(
    resolveThumbnailCandidates(
      [
        { fileUrl: "https://example.org/same.jpg", width: 100, height: 100 },
        { fileUrl: "/same.jpg", width: 900, height: 500 },
        { fileUrl: "/other.jpg", width: -1, height: 200 },
        { fileUrl: "data:image/png,abc", width: 1000, height: 1000 },
        { fileUrl: "  " },
        123,
        null
      ],
      "example.org",
      "https:"
    ),
    [
      { url: "https://example.org/same.jpg", width: 900, height: 500 },
      { url: "https://example.org/other.jpg", width: null, height: 200 }
    ]
  );
});

test("legacy compatibility uses detail legacy then list thumbnails then list legacy without preview", () => {
  assert.deepEqual(
    resolveLegacyThumbnailCompatibility(
      { thumbnailPath: "/detail.jpg", previewPath: "/detail-preview.jpg" },
      { thumbnails: [{ fileUrl: "/list-modern.jpg", width: 900, height: 500 }] },
      "example.org",
      "https:"
    ),
    { url: "https://example.org/detail.jpg", width: null, height: null }
  );
  assert.deepEqual(
    resolveLegacyThumbnailCompatibility(
      { previewPath: "/detail-preview.jpg" },
      { thumbnails: [{ fileUrl: "/list-modern.jpg", width: 900, height: 500 }] },
      "example.org",
      "https:"
    ),
    { url: "https://example.org/list-modern.jpg", width: 900, height: 500 }
  );
  assert.deepEqual(
    resolveLegacyThumbnailCompatibility(
      { previewPath: "/detail-preview.jpg" },
      { previewPath: "/list-preview.jpg" },
      "example.org",
      "https:"
    ),
    { url: null, width: null, height: null }
  );
});
