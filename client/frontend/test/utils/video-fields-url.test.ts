/**
 * Regression tests for canonical video detail URL construction.
 */

import { describe, expect, it } from "vitest";
import { videoPageUrl } from "../../src/utils/video-fields";
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
