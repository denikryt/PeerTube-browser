/** Characterization and regression tests for PeerTube thumbnail selection. */

import assert from "node:assert/strict";
import test from "node:test";

import {
  resolvePeerTubeMediaUrl,
  resolvePreferredThumbnail,
  resolvePreferredThumbnailUrl
} from "../src/video-media.js";

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

test("resolvePreferredThumbnail selects the largest modern detail thumbnail and dimensions", () => {
  assert.deepEqual(
    resolvePreferredThumbnail(
      {
        thumbnails: [
          { fileUrl: "/thumb-small.jpg", width: 320, height: 180 },
          { fileUrl: "/thumb-large.jpg", width: 1280, height: 720 },
          { fileUrl: "/thumb-equal-later.jpg", width: 1280, height: 720 }
        ],
        thumbnailPath: "/legacy.jpg"
      },
      { thumbnailUrl: "https://example.org/stale.jpg" },
      "example.org",
      "https:"
    ),
    {
      url: "https://example.org/thumb-large.jpg",
      width: 1280,
      height: 720
    }
  );
});

test("resolvePreferredThumbnail prefers detail legacy thumbnail before list modern thumbnails", () => {
  assert.deepEqual(
    resolvePreferredThumbnail(
      { thumbnailPath: "/detail.jpg" },
      { thumbnails: [{ fileUrl: "/list-modern.jpg", width: 1920, height: 1080 }] },
      "example.org",
      "https:"
    ),
    { url: "https://example.org/detail.jpg", width: null, height: null }
  );
});

test("resolvePreferredThumbnail falls back through list media before preview fields", () => {
  assert.deepEqual(
    resolvePreferredThumbnail(
      { previewPath: "/detail-preview.jpg" },
      { thumbnailUrl: "https://example.org/list.jpg" },
      "example.org",
      "https:"
    ),
    { url: "https://example.org/list.jpg", width: null, height: null }
  );
});

test("resolvePreferredThumbnailUrl preserves the existing URL-only caller contract", () => {
  assert.equal(
    resolvePreferredThumbnailUrl(
      { previewPath: "/lazy-static/thumbnails/preview.jpg" },
      {},
      "example.org",
      "https:"
    ),
    "https://example.org/lazy-static/thumbnails/preview.jpg"
  );
});
