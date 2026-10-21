import { readFileSync } from "node:fs";
import { join } from "node:path";
/** Search state regressions for video filters and continuation. */
import { describe, expect, it, vi } from "vitest";
import { useSearch } from "../../src/composables/useSearch";

function ok(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}
function fail(status: number, body: unknown) {
  return { ok: false, status, json: async () => body };
}

describe("Search pagination state", () => {
  it("sends shared filters only to video search and appends one cursor page", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/search/channels")) {
        return ok({ items: [], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_channels", query: "linux" } });
      }
      if (url.includes("cursor=next")) {
        return ok({ items: [{ video_id: "b", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_videos", query: "linux" } });
      }
      return ok({ items: [{ video_id: "a", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: "next", has_more: true }, meta: { source: "search_videos", query: "linux" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const search = useSearch();
    const filters = { language: "uk", category: "Education", tag: "linux", instance: "example.org" };

    await search.search("linux", filters);
    await search.loadMore();

    expect(search.state.videos.map((item) => item.video_id)).toEqual(["a", "b"]);
    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    const videoUrls = urls.filter((url) => url.includes("/search/videos"));
    const channelUrl = urls.find((url) => url.includes("/search/channels"))!;
    expect(videoUrls[0]).toContain("language=uk");
    expect(videoUrls[0]).toContain("category=Education");
    expect(channelUrl).not.toContain("language=");
    expect(channelUrl).not.toContain("category=");
  });

  it("keeps existing video rows/cursor and pauses automatic continuation after failure", async () => {
    const responses = [
      ok({ items: [{ video_id: "a", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: "next", has_more: true }, meta: { source: "search_videos", query: "linux" } }),
      ok({ items: [], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_channels", query: "linux" } }),
      fail(502, { error: "temporary" })
    ];
    const fetchMock = vi.fn(async () => responses.shift()!);
    vi.stubGlobal("fetch", fetchMock);
    const search = useSearch();

    await search.search("linux", { language: null, category: null, tag: null, instance: null });
    await search.loadMore();

    expect(search.state.videos.map((item) => item.video_id)).toEqual(["a"]);
    expect(search.state.nextCursor).toBe("next");
    expect(search.state.nextPageError).toBeTruthy();

    await search.loadMore();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("retries the same video cursor and suppresses overlapping continuation requests", async () => {
    let resolveMore!: (value: ReturnType<typeof ok>) => void;
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/search/channels")) {
        return Promise.resolve(ok({ items: [], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_channels", query: "linux" } }));
      }
      if (url.includes("cursor=next")) {
        return new Promise<ReturnType<typeof ok>>((resolve) => { resolveMore = resolve; });
      }
      return Promise.resolve(ok({
        items: [{ video_id: "a", instance_domain: "example.org" }],
        pagination: { limit: 20, next_cursor: "next", has_more: true },
        meta: { source: "search_videos", query: "linux" }
      }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const search = useSearch();

    await search.search("linux", { language: null, category: null, tag: null, instance: null });
    const firstMore = search.loadMore();
    const overlap = search.loadMore();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/search/videos")).length).toBe(2);
    resolveMore(ok({
      items: [{ video_id: "b", instance_domain: "example.org" }],
      pagination: { limit: 20, next_cursor: null, has_more: false },
      meta: { source: "search_videos", query: "linux" }
    }));
    await Promise.all([firstMore, overlap]);
    expect(search.state.videos.map((item) => item.video_id)).toEqual(["a", "b"]);
    expect(search.canLoadMore.value).toBe(false);
  });

  it("discards late video/channel results after q or filter selection changes", async () => {
    let resolveOldVideo!: (value: ReturnType<typeof ok>) => void;
    let resolveOldChannel!: (value: ReturnType<typeof ok>) => void;
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("q=old") && url.includes("/search/videos")) {
        return new Promise<ReturnType<typeof ok>>((resolve) => { resolveOldVideo = resolve; });
      }
      if (url.includes("q=old") && url.includes("/search/channels")) {
        return new Promise<ReturnType<typeof ok>>((resolve) => { resolveOldChannel = resolve; });
      }
      if (url.includes("/search/channels")) {
        return Promise.resolve(ok({ items: [{ channel_id: "new-channel", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_channels", query: "new" } }));
      }
      return Promise.resolve(ok({ items: [{ video_id: "new-video", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_videos", query: "new" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const search = useSearch();
    const filters = { language: null, category: null, tag: null, instance: null };

    const old = search.search("old", filters);
    await Promise.resolve();
    await search.search("new", { ...filters, category: "Education" });
    resolveOldVideo(ok({ items: [{ video_id: "old-video", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_videos", query: "old" } }));
    resolveOldChannel(ok({ items: [{ channel_id: "old-channel", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_channels", query: "old" } }));
    await old;

    expect(search.state.q).toBe("new");
    expect(search.state.videos.map((item) => item.video_id)).toEqual(["new-video"]);
    expect(search.state.channels.map((item) => item.channel_id)).toEqual(["new-channel"]);
  });


  it("resets continuation loading when a new search supersedes an in-flight old page", async () => {
    let resolveOldMore!: (value: ReturnType<typeof ok>) => void;
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("q=old") && url.includes("cursor=old-next")) {
        return new Promise<ReturnType<typeof ok>>((resolve) => { resolveOldMore = resolve; });
      }
      if (url.includes("q=old") && url.includes("/search/channels")) {
        return Promise.resolve(ok({ items: [], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_channels", query: "old" } }));
      }
      if (url.includes("q=old")) {
        return Promise.resolve(ok({ items: [{ video_id: "old-a", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: "old-next", has_more: true }, meta: { source: "search_videos", query: "old" } }));
      }
      if (url.includes("q=new") && url.includes("cursor=new-next")) {
        return Promise.resolve(ok({ items: [{ video_id: "new-b", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_videos", query: "new" } }));
      }
      if (url.includes("/search/channels")) {
        return Promise.resolve(ok({ items: [], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_channels", query: "new" } }));
      }
      return Promise.resolve(ok({ items: [{ video_id: "new-a", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: "new-next", has_more: true }, meta: { source: "search_videos", query: "new" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const search = useSearch();
    const filters = { language: null, category: null, tag: null, instance: null };

    await search.search("old", filters);
    const oldMore = search.loadMore();
    expect(search.state.loadingMore).toBe(true);

    await search.search("new", { ...filters, category: "Education" });
    expect(search.state.loadingMore).toBe(false);
    expect(search.state.videos.map((item) => item.video_id)).toEqual(["new-a"]);

    resolveOldMore(ok({ items: [{ video_id: "old-b", instance_domain: "example.org" }], pagination: { limit: 20, next_cursor: null, has_more: false }, meta: { source: "search_videos", query: "old" } }));
    await oldMore;

    expect(search.state.loadingMore).toBe(false);
    expect(search.state.videos.map((item) => item.video_id)).toEqual(["new-a"]);
    await search.loadMore();
    expect(search.state.videos.map((item) => item.video_id)).toEqual(["new-a", "new-b"]);
  });

  it("delegates shared filter controls while Search retains URL and observer ownership", () => {
    const source = readFileSync(join(process.cwd(), "src", "views", "SearchView.vue"), "utf8");
    expect(source).toContain("<VideoFilterControls");
    expect(source).toContain('@change="setFilters"');
    expect(source).toContain("void search(routeQuery.value, filters.value)");
    expect(source).toContain("new IntersectionObserver");
    expect(source).toContain("void loadMore()");
    expect(source).toContain("disconnectObserver");
    expect(source).not.toContain("state.nextCursor =");
    expect(source).not.toContain("fetchVideoFacetsPayload");
    expect(source).not.toContain("facetsLoading");
    const composable = readFileSync(join(process.cwd(), "src", "composables", "useSearch.ts"), "utf8");
    expect(composable).not.toContain("networkHasMore");
    expect(composable).not.toContain("autoLoadPaused");
    expect(composable).not.toContain("selectionKey");
  });

});
