/**
 * Search API v1 frontend URL boundary tests.
 */

import { describe, expect, it } from "vitest";
import { buildChannelSearchUrl, buildVideoSearchUrl } from "../../src/data/search";

describe("search data helpers", () => {
  it("build Client backend v1 search URLs only", () => {
    expect(buildVideoSearchUrl({ q: "linux", apiBase: "https://client.example", limit: 5 })).toBe(
      "https://client.example/api/v1/search/videos?q=linux&limit=5"
    );
    expect(buildChannelSearchUrl({ q: "linux", apiBase: "https://client.example", cursor: "abc" })).toBe(
      "https://client.example/api/v1/search/channels?q=linux&cursor=abc"
    );
  });
});
