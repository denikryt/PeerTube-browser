/**
 * Regression tests for canonical video URL and thumbnail field resolution.
 */

import { describe, expect, it } from "vitest";
import {
  appendUniqueVideoRows,
  dedupeVideoRows,
  thumbnailCandidates,
  thumbnailUrl,
  thumbnailUrls,
  videoPageUrl,
  videoRowKey
} from "../../src/utils/video-fields";
import type { VideoRow } from "../../src/types/videos";

describe("video detail URL construction", () => {
  it("uses the new host-scoped Vue route with UUID preference", () => {
    const row: VideoRow = {
      video_id: "numeric-id",
      video_uuid: "uuid-id",
      instance_domain: "example.org"
    };

    expect(videoPageUrl(row)).toBe("/video/example.org/uuid-id");
  });
});

describe("video card thumbnail URL resolution", () => {
  it("keeps candidate dimensions and exposes object candidates to thumbnail renderers", () => {
    const row: VideoRow = {
      thumbnail_candidates: [
        { url: "https://example.org/large.jpg", width: 1280, height: 720 },
        { url: "https://example.org/medium.jpg", width: 850, height: 480 },
        { url: "https://example.org/unknown.jpg", width: null, height: null },
        { url: "https://example.org/medium.jpg", width: 850, height: 480 }
      ]
    };

    expect(thumbnailCandidates(row)).toEqual([
      { url: "https://example.org/large.jpg", width: 1280, height: 720 },
      { url: "https://example.org/medium.jpg", width: 850, height: 480 },
      { url: "https://example.org/unknown.jpg", width: null, height: null }
    ]);
    expect(thumbnailUrls(row)).toEqual([
      "https://example.org/large.jpg",
      "https://example.org/medium.jpg",
      "https://example.org/unknown.jpg"
    ]);
  });

  it("uses the ordered thumbnail_urls list and mirrors its first candidate", () => {
    const row = {
      thumbnail_urls: [
        "https://example.org/large.jpg",
        "https://example.org/small.jpg",
        "https://example.org/large.jpg"
      ],
      thumbnail_url: "https://example.org/legacy.jpg"
    };
    expect(thumbnailUrls(row)).toEqual([
      "https://example.org/large.jpg",
      "https://example.org/small.jpg"
    ]);
    expect(thumbnailUrl(row)).toBe("https://example.org/large.jpg");
  });

  it("keeps singular snake/camel aliases as legacy fallback when the list is absent", () => {
    expect(thumbnailUrls({ thumbnail_url: "https://example.org/thumb.jpg" })).toEqual(["https://example.org/thumb.jpg"]);
    expect(thumbnailUrl({ thumbnailUrl: "https://example.org/thumb-alias.jpg" })).toBe("https://example.org/thumb-alias.jpg");
  });

  it("treats an explicit empty list as authoritative and never falls back to singular or preview", () => {
    const row = {
      thumbnail_urls: [],
      thumbnail_url: "https://example.org/legacy.jpg",
      preview_path: "/lazy-static/previews/a.jpg"
    };
    expect(thumbnailUrls(row)).toEqual([]);
    expect(thumbnailUrl(row)).toBeNull();
  });

  it("does not fallback to source preview_path fields", () => {
    const row = { preview_path: "/lazy-static/previews/a.jpg", previewPath: "/lazy-static/previews/b.jpg" };
    expect(thumbnailUrls(row)).toEqual([]);
    expect(thumbnailUrl(row)).toBeNull();
  });
});

describe("video row identity and duplicate guards", () => {
  it("deduplicates compatibility aliases for the same host-scoped video", () => {
    const rows: VideoRow[] = [
      { instance_domain: "example.org", video_uuid: "abc", title: "first" },
      { instanceDomain: "example.org", videoUuid: "abc", title: "duplicate" }
    ];

    expect(videoRowKey(rows[0])).toBe("example.org::abc");
    expect(dedupeVideoRows(rows)).toEqual([rows[0]]);
  });

  it("keeps the same video id from different instances and appends only unseen rows", () => {
    const target: VideoRow[] = [{ instance_domain: "one.example", video_id: "42" }];
    const incoming: VideoRow[] = [
      { instanceDomain: "one.example", video_id: "42" },
      { instance_domain: "two.example", video_id: "42" },
      { instance_domain: "three.example", video_numeric_id: 42 }
    ];

    appendUniqueVideoRows(target, incoming);

    expect(target.map(videoRowKey)).toEqual(["one.example::42", "two.example::42", "three.example::42"]);
  });
});
