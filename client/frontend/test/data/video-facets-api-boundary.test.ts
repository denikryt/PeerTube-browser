/** Browser -> Client global video-facets boundary tests. */
import { describe, expect, it, vi } from "vitest";
import { buildVideoFacetsUrl, fetchVideoFacetsPayload } from "../../src/data/video-facets";

describe("video facets data boundary", () => {
  it("uses the public Client facet resource only", () => {
    const url = buildVideoFacetsUrl("https://client.example");
    expect(url).toBe("https://client.example/api/v1/video-facets");
    expect(url).not.toContain("/internal/");
  });

  it("fails independently with an HTTP error when the facet resource is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 502, json: async () => ({ error: "facets unavailable" }) })));
    await expect(fetchVideoFacetsPayload()).rejects.toThrow("facets unavailable");
  });
});
