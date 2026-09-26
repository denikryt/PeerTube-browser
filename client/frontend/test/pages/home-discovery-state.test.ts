/** Stateful Home feed regression tests for finite Recommended and paged providers. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { useFeed } from "../../src/composables/useFeed";

function ok(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}
function fail(status: number, body: unknown) {
  return { ok: false, status, json: async () => body };
}
function row(id: string) {
  return { video_id: id, instance_domain: "example.org", title: id };
}

describe("Home feed state", () => {
  it("fetches Recommended once and reveals the finite buffer locally", async () => {
    const fetchMock = vi.fn(async () => ok({
      items: Array.from({ length: 45 }, (_, index) => row(String(index))),
      pagination: { limit: 50, next_cursor: null, has_more: false },
      meta: { source: "recommendations", filters: { language: null, category: null, tag: null, instance: null } }
    }));
    vi.stubGlobal("fetch", fetchMock);
    const feed = useFeed();

    await feed.loadSelection("recommendations", { language: null, category: null, tag: null, instance: null });
    expect(feed.visibleItems.value).toHaveLength(20);
    expect(feed.canLoadMore.value).toBe(true);

    await feed.loadMore();
    await feed.loadMore();
    expect(feed.visibleItems.value).toHaveLength(45);
    expect(feed.canLoadMore.value).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("limit=50");
  });

  it("reuses a cached selection without refetch and force reload explicitly invalidates it", async () => {
    const fetchMock = vi.fn(async () => ok({
      items: [row("cached")],
      pagination: { limit: 20, next_cursor: null, has_more: false },
      meta: { source: "fresh" }
    }));
    vi.stubGlobal("fetch", fetchMock);
    const feed = useFeed();
    const filters = { language: null, category: null, tag: null, instance: null };

    await feed.loadSelection("fresh", filters);
    await feed.loadSelection("fresh", filters);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(feed.state.items.map((item) => item.video_id)).toEqual(["cached"]);

    await feed.loadSelection("fresh", filters, true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("preserves paged rows/cursor on ordinary failure and stale Random resets from page one", async () => {
    const responses = [
      ok({ items: [row("a")], pagination: { limit: 20, next_cursor: "next-a", has_more: true }, meta: { source: "random" } }),
      fail(503, { error: "temporary", code: "V1_DISCOVERY_PROVIDER_UNAVAILABLE" }),
      ok({ items: [row("a")], pagination: { limit: 20, next_cursor: "next-a", has_more: true }, meta: { source: "random" } }),
      fail(400, { error: "stale", code: "V1_DISCOVERY_STALE_CURSOR" }),
      ok({ items: [row("fresh-a")], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "random" } })
    ];
    const fetchMock = vi.fn(async () => responses.shift()!);
    vi.stubGlobal("fetch", fetchMock);
    const feed = useFeed();
    const filters = { language: null, category: null, tag: null, instance: null };

    await feed.loadSelection("random", filters);
    await feed.loadMore();
    expect(feed.state.items.map((item) => item.video_id)).toEqual(["a"]);
    expect(feed.state.nextCursor).toBe("next-a");
    expect(feed.state.nextPageError).toBeTruthy();

    await feed.loadMore();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await feed.retryNextPage();
    expect(feed.state.nextPageError).toBe("");
    expect(feed.state.nextCursor).toBe("next-a");
    expect(feed.state.items.map((item) => item.video_id)).toEqual(["a"]);

    await feed.loadMore();
    expect(feed.state.items.map((item) => item.video_id)).toEqual(["fresh-a"]);
    expect(feed.state.nextCursor).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(5);
    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls[1]).toContain("cursor=next-a");
    expect(urls[2]).toContain("cursor=next-a");
    expect(urls[3]).toContain("cursor=next-a");
    expect(urls[4]).not.toContain("cursor=");
  });

  it("suppresses overlapping continuation and ignores late responses from an older selection", async () => {
    let resolveContinuation!: (value: ReturnType<typeof ok>) => void;
    let resolveOldSelection!: (value: ReturnType<typeof ok>) => void;
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/fresh") && !url.includes("cursor=")) {
        if (url.includes("language=uk")) {
          return new Promise<ReturnType<typeof ok>>((resolve) => { resolveOldSelection = resolve; });
        }
        return Promise.resolve(ok({
          items: [row("first")],
          pagination: { limit: 20, next_cursor: "next", has_more: true },
          meta: { source: "fresh" }
        }));
      }
      if (url.includes("/fresh") && url.includes("cursor=next")) {
        return new Promise<ReturnType<typeof ok>>((resolve) => { resolveContinuation = resolve; });
      }
      return Promise.resolve(ok({
        items: [row("popular")],
        pagination: { limit: 20, next_cursor: null, has_more: false },
        meta: { source: "popular" }
      }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const feed = useFeed();
    const empty = { language: null, category: null, tag: null, instance: null };

    await feed.loadSelection("fresh", empty);
    const firstMore = feed.loadMore();
    const overlapping = feed.loadMore();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveContinuation(ok({
      items: [row("second")],
      pagination: { limit: 20, next_cursor: null, has_more: false },
      meta: { source: "fresh" }
    }));
    await Promise.all([firstMore, overlapping]);
    expect(feed.state.items.map((item) => item.video_id)).toEqual(["first", "second"]);

    const oldSelection = feed.loadSelection("fresh", { ...empty, language: "uk" });
    await Promise.resolve();
    await feed.loadSelection("popular", empty);
    resolveOldSelection(ok({
      items: [row("late-fresh")],
      pagination: { limit: 20, next_cursor: null, has_more: false },
      meta: { source: "fresh" }
    }));
    await oldSelection;
    expect(feed.state.mode).toBe("popular");
    expect(feed.state.items.map((item) => item.video_id)).toEqual(["popular"]);
  });

  it("allows an in-flight page to finish and reuses the completed selection after Home deactivation", async () => {
    let resolveHidden!: (value: ReturnType<typeof ok>) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(ok({
        items: [row("first")],
        pagination: { limit: 20, next_cursor: "next", has_more: true },
        meta: { source: "fresh" }
      }))
      .mockImplementationOnce(() => new Promise<ReturnType<typeof ok>>((resolve) => { resolveHidden = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const feed = useFeed();
    const filters = { language: null, category: null, tag: null, instance: null };

    await feed.loadSelection("fresh", filters);
    const hidden = feed.loadMore();
    resolveHidden(ok({
      items: [row("second")],
      pagination: { limit: 20, next_cursor: null, has_more: false },
      meta: { source: "fresh" }
    }));
    await hidden;

    expect(feed.state.items.map((item) => item.video_id)).toEqual(["first", "second"]);
    expect(feed.state.nextCursor).toBeNull();
    expect(feed.state.loadingMore).toBe(false);

    await feed.loadSelection("fresh", filters);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(feed.state.items.map((item) => item.video_id)).toEqual(["first", "second"]);
  });

  it("keeps first-page error distinct from empty and terminal state cannot issue continuation", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/popular")) return fail(503, { error: "provider unavailable" });
      return ok({
        items: [row("only")],
        pagination: { limit: 20, next_cursor: null, has_more: false },
        meta: { source: "fresh" }
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const feed = useFeed();
    const empty = { language: null, category: null, tag: null, instance: null };

    await feed.loadSelection("fresh", empty);
    expect(feed.canLoadMore.value).toBe(false);
    await feed.loadMore();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await feed.loadSelection("popular", empty);
    expect(feed.state.items).toEqual([]);
    expect(feed.state.error).toContain("provider unavailable");
    expect(feed.isEmpty.value).toBe(false);
  });
});

const homeSource = readFileSync(join(process.cwd(), "src", "views", "HomeView.vue"), "utf8");
const appSource = readFileSync(join(process.cwd(), "src", "App.vue"), "utf8");
const filterControlsSource = readFileSync(join(process.cwd(), "src", "components", "VideoFilterControls.vue"), "utf8");

describe("Home observer/cache ownership", () => {
  it("keeps the observer in Home and delegates continuation only to loadMore", () => {
    expect(homeSource).toContain("new IntersectionObserver");
    expect(homeSource).toContain("void loadMore()");
    expect(homeSource).toContain("onActivated");
    expect(homeSource).toContain("onDeactivated");
    expect(homeSource).toContain("onUnmounted");
    expect(homeSource).toContain("disconnectObserver()");
    expect(homeSource).not.toContain("suspend()");
    expect(homeSource).toContain("if (!active || !sentinel.value");
    expect(homeSource).not.toContain("state.nextCursor =");
    expect(homeSource).not.toContain("fetchDiscoveryPayload");
  });

  it("delegates shared filter controls while Home retains URL selection ownership", () => {
    expect(homeSource).toContain("<VideoFilterControls");
    expect(homeSource).toContain('@change="setFilters"');
    expect(homeSource).toContain("void ensureRouteSelection()");
    expect(homeSource).not.toContain("fetchVideoFacetsPayload");
    expect(homeSource).not.toContain("facetsLoading");
  });

  it("keeps facet loading and selected-value fallback inside the shared filter component", () => {
    expect(filterControlsSource).toContain("fetchVideoFacetsPayload");
    expect(filterControlsSource).toContain("facetsLoading");
    expect(filterControlsSource).toContain("facetsError");
    expect(filterControlsSource).toContain("!facets?.languages.some");
    expect(filterControlsSource).toContain("!facets?.categories.some");
    expect(filterControlsSource).toContain('emit("change"');
  });

  it("caches only Home and retains the two required finite Recommended markers", () => {
    expect(appSource).toContain("<KeepAlive>");
    expect(appSource).toContain("route.name === 'home'");
    const composable = readFileSync(join(process.cwd(), "src", "composables", "useFeed.ts"), "utf8");
    expect(composable).toContain("TEMP-DISCOVERY-RECOMMENDATIONS: buffer the one-shot finite recommendation batch for local paging");
    expect(composable).toContain("TEMP-DISCOVERY-RECOMMENDATIONS: reveal the one-shot finite recommendation batch locally");
    expect(composable).not.toContain("networkHasMore");
    expect(composable).not.toContain("autoLoadPaused");
  });
});
