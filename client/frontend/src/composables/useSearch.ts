/** Stateful Search v1 loader with video-filter-owned cursor continuation. */
import { computed, reactive } from "vue";
import { fetchChannelSearchPayload, fetchVideoSearchPayload } from "../data/search";
import { emptyVideoFilters } from "../state/video-filters";
import type { ChannelRow } from "../types/channels";
import type { VideoFilters } from "../types/video-filters";
import type { VideoRow } from "../types/videos";
import { appendUniqueVideoRows, dedupeVideoRows } from "../utils/video-fields";

const PAGE_SIZE = 20;

type SearchState = {
  q: string;
  filters: VideoFilters;
  videos: VideoRow[];
  channels: ChannelRow[];
  loadingVideos: boolean;
  loadingChannels: boolean;
  loadingMore: boolean;
  videoError: string;
  channelError: string;
  nextPageError: string;
  nextCursor: string | null;
  requestGeneration: number;
};

/** Create Search state with video and channel requests kept deliberately separate. */
export function useSearch() {
  const state = reactive<SearchState>({
    q: "",
    filters: emptyVideoFilters(),
    videos: [],
    channels: [],
    loadingVideos: false,
    loadingChannels: false,
    loadingMore: false,
    videoError: "",
    channelError: "",
    nextPageError: "",
    nextCursor: null,
    requestGeneration: 0
  });

  const canLoadMore = computed(() => Boolean(state.nextCursor));

  /** Reset and load video page one plus the existing query-only channel search. */
  async function search(query: string, filters: VideoFilters = emptyVideoFilters()): Promise<void> {
    const q = query.trim();
    const generation = ++state.requestGeneration;
    state.q = q;
    state.filters = { ...filters };
    state.videos = [];
    state.channels = [];
    state.videoError = "";
    state.channelError = "";
    state.nextPageError = "";
    state.nextCursor = null;
    // A new selection owns a new generation. Any in-flight continuation from
    // the prior generation can no longer clear this flag in its guarded finally.
    state.loadingMore = false;
    if (!q) {
      state.loadingVideos = false;
      state.loadingChannels = false;
      return;
    }

    state.loadingVideos = true;
    state.loadingChannels = true;
    const [videoResult, channelResult] = await Promise.allSettled([
      fetchVideoSearchPayload({ q, limit: PAGE_SIZE, filters }),
      fetchChannelSearchPayload({ q, limit: PAGE_SIZE })
    ]);
    if (generation !== state.requestGeneration) return;

    if (videoResult.status === "fulfilled") {
      state.videos = dedupeVideoRows(videoResult.value.items ?? []);
      state.nextCursor = videoResult.value.pagination?.has_more
        ? videoResult.value.pagination?.next_cursor ?? null
        : null;
    } else {
      state.videoError = errorMessage(videoResult.reason, "Video search failed");
    }
    if (channelResult.status === "fulfilled") {
      state.channels = channelResult.value.items ?? [];
    } else {
      state.channelError = errorMessage(channelResult.reason, "Channel search failed");
    }
    state.loadingVideos = false;
    state.loadingChannels = false;
  }

  /** Load one video-only continuation page; channel results are not paged here. */
  async function loadMore(): Promise<void> {
    if (state.loadingVideos || state.loadingMore || state.nextPageError || !state.nextCursor) return;
    const generation = state.requestGeneration;
    const cursor = state.nextCursor;
    const q = state.q;
    const filters = { ...state.filters };
    state.loadingMore = true;
    state.nextPageError = "";
    try {
      const payload = await fetchVideoSearchPayload({ q, limit: PAGE_SIZE, cursor, filters });
      if (generation !== state.requestGeneration) return;
      appendUniqueVideoRows(state.videos, payload.items ?? []);
      state.nextCursor = payload.pagination?.has_more
        ? payload.pagination?.next_cursor ?? null
        : null;
    } catch (error) {
      if (generation !== state.requestGeneration) return;
      // Do not consume the cursor on failure. Explicit Retry must request the
      // exact same continuation rather than silently skipping a page.
      state.nextPageError = errorMessage(error, "Video search continuation failed");
    } finally {
      if (generation === state.requestGeneration) state.loadingMore = false;
    }
  }

  /** Retry an ordinary video continuation with the same public cursor. */
  async function retryNextPage(): Promise<void> {
    if (!state.nextPageError) return;
    state.nextPageError = "";
    await loadMore();
  }

  return { state, canLoadMore, search, loadMore, retryNextPage };
}

/** Convert unknown transport failures to one user-facing message. */
function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
