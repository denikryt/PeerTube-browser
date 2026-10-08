/** Regression tests for PeerTube thumbnail candidate normalization. */

import assert from "node:assert/strict";
import test from "node:test";

import {
  projectDetailThumbnailCandidates,
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

test("full detail projection requires a structurally recognized thumbnail representation", () => {
  assert.equal(
    projectDetailThumbnailCandidates({}, "example.org", "https:"),
    null
  );
  assert.equal(
    projectDetailThumbnailCandidates({ thumbnails: {} }, "example.org", "https:"),
    null
  );
  for (const value of [null, "", "   ", 123, false, {}, []]) {
    assert.equal(
      projectDetailThumbnailCandidates({ thumbnailPath: value }, "example.org", "https:"),
      null
    );
  }
});

test("full detail projection treats an actual modern array as authoritative and never falls through", () => {
  assert.deepEqual(
    projectDetailThumbnailCandidates(
      { thumbnails: [], thumbnailPath: "/legacy.jpg" },
      "example.org",
      "https:"
    ),
    []
  );
  assert.deepEqual(
    projectDetailThumbnailCandidates(
      {
        thumbnails: [
          { fileUrl: "/small.jpg", width: 100, height: 100 },
          { fileUrl: "/large.jpg", width: 800, height: 450 },
          { fileUrl: "https://example.org/large.jpg", width: 300, height: 200 }
        ],
        thumbnailPath: "/legacy.jpg"
      },
      "example.org",
      "https:"
    ),
    [
      { url: "https://example.org/large.jpg", width: 800, height: 450 },
      { url: "https://example.org/small.jpg", width: 100, height: 100 }
    ]
  );
});

test("full detail projection falls through malformed modern shape to usable legacy fields", () => {
  assert.deepEqual(
    projectDetailThumbnailCandidates(
      { thumbnails: { unexpected: true }, thumbnailPath: "/legacy.jpg" },
      "example.org",
      "https:"
    ),
    [{ url: "https://example.org/legacy.jpg", width: null, height: null }]
  );
  assert.deepEqual(
    projectDetailThumbnailCandidates(
      { thumbnailPath: { fileUrl: "/legacy-object.jpg" } },
      "example.org",
      "https:"
    ),
    [{ url: "https://example.org/legacy-object.jpg", width: null, height: null }]
  );
});

test("recognized explicit non-http legacy references are authoritative policy rejections", () => {
  for (const value of ["file:///tmp/a.jpg", "data:image/png,abc", "ftp://example.org/a.jpg"]) {
    assert.deepEqual(
      projectDetailThumbnailCandidates({ thumbnailPath: value }, "example.org", "https:"),
      []
    );
  }
  for (const value of ["http:", "https:", "http://", "https://"]) {
    assert.equal(
      projectDetailThumbnailCandidates({ thumbnailPath: value }, "example.org", "https:"),
      null
    );
  }
});

test("preview-only detail never establishes card-thumbnail authority", () => {
  assert.equal(
    projectDetailThumbnailCandidates(
      { previewPath: "/preview.jpg", previewUrl: "https://example.org/preview.jpg" },
      "example.org",
      "https:"
    ),
    null
  );
});
