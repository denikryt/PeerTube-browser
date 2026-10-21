/**
 * Regression tests for canonical video URL and thumbnail field resolution.
 */

import { describe, expect, it } from "vitest";
import {
  appendUniqueVideoRows,
  dedupeVideoRows,
  thumbnailUrl,
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
  it("uses canonical snake_case thumbnail_url when present", () => {
    expect(thumbnailUrl({ thumbnail_url: "https://example.org/thumb.jpg" })).toBe("https://example.org/thumb.jpg");
  });

  it("keeps the existing camelCase thumbnailUrl alias fallback", () => {
    expect(thumbnailUrl({ thumbnailUrl: "https://example.org/thumb-alias.jpg" })).toBe("https://example.org/thumb-alias.jpg");
  });

  it("does not fallback to source preview_path fields", () => {
    expect(thumbnailUrl({ preview_path: "/lazy-static/previews/a.jpg", previewPath: "/lazy-static/previews/b.jpg" })).toBeNull();
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
