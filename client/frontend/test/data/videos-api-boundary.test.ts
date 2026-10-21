import { describe, expect, it } from "vitest";

import { buildSimilarUrl } from "../../src/data/videos";

describe("video-detail Similar API boundary", () => {
  it("builds only the video-detail Similar Client endpoint", () => {
    const url = new URL(buildSimilarUrl({
      id: "video-123",
      host: "videos.example",
      limit: "8",
      apiBase: "http://client.local:5174"
    }));

    expect(url.pathname).toBe("/api/v1/videos/video-123/similar");
    expect(url.searchParams.get("host")).toBe("videos.example");
    expect(url.searchParams.get("limit")).toBe("8");
  });

  it("rejects a missing video identity instead of falling through to Discovery", () => {
    expect(() => buildSimilarUrl({ apiBase: "http://client.local:5174" })).toThrow(
      "Similar video id is required"
    );
  });
});
