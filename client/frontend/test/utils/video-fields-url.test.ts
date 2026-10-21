/**
 * Regression tests for canonical video URL and thumbnail field resolution.
 */

import { describe, expect, it } from "vitest";
import { thumbnailUrl, videoPageUrl } from "../../src/utils/video-fields";
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
