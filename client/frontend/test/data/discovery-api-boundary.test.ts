/** Browser -> Client Discovery v1 boundary regression tests. */
import { describe, expect, it, vi } from "vitest";
import {
  DiscoveryApiError,
  buildDiscoveryUrl,
  fetchDiscoveryPayload
} from "../../src/data/discovery";

describe("Discovery data boundary", () => {
  it("builds only public Client URLs with all selected filters and cursor", () => {
    const url = buildDiscoveryUrl("trending", {
      apiBase: "https://client.example",
      limit: 20,
      cursor: "opaque",
      filters: { language: "uk", category: "Education", tag: "linux", instance: "example.org" }
    });

    expect(url).toBe("https://client.example/api/v1/discovery/trending?limit=20&cursor=opaque&language=uk&category=Education&tag=linux&instance=example.org");
    expect(url).not.toContain("/internal/");
  });

  it("preserves machine-readable Client errors instead of collapsing stale cursors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: "Discovery cursor is stale", code: "V1_DISCOVERY_STALE_CURSOR" })
    })));

    await expect(fetchDiscoveryPayload("random", { limit: 20 })).rejects.toMatchObject({
      name: "DiscoveryApiError",
      code: "V1_DISCOVERY_STALE_CURSOR",
      status: 400
    } satisfies Partial<DiscoveryApiError>);
  });
});
