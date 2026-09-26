/** Stateful Home Discovery loader with provider-owned continuation cursors. */
import { computed, reactive } from "vue";
import { DiscoveryApiError, fetchDiscoveryPayload } from "../data/discovery";
import { emptyVideoFilters, homeSelectionKey, type HomeMode } from "../state/video-filters";
import type { VideoFilters } from "../types/video-filters";
import type { VideoRow } from "../types/videos";
import { appendUniqueVideoRows, dedupeVideoRows } from "../utils/video-fields";

const PAGE_SIZE = 20;
const RECOMMENDATION_FETCH_LIMIT = 50;

type FeedState = {
  mode: HomeMode;
  filters: VideoFilters;
  items: VideoRow[];
  recommendationBuffer: VideoRow[];
  recommendationVisibleCount: number;
  nextCursor: string | null;
  initialLoading: boolean;
  loadingMore: boolean;
  error: string;
  nextPageError: string;
  selectionKey: string;
  requestGeneration: number;
  initialized: boolean;
};

/** Create Home feed state while keeping cursors entirely inside the composable. */
export function useFeed() {
  const state = reactive<FeedState>({
    mode: "recommendations",
    filters: emptyVideoFilters(),
    items: [],
    recommendationBuffer: [],
    recommendationVisibleCount: 0,
    nextCursor: null,
    initialLoading: false,
    loadingMore: false,
    error: "",
    nextPageError: "",
    selectionKey: "",
    requestGeneration: 0,
    initialized: false
  });

  const visibleItems = computed(() => (
    state.mode === "recommendations"
      ? state.recommendationBuffer.slice(0, state.recommendationVisibleCount)
      : state.items
  ));
  const canLoadMore = computed(() => (
    state.mode === "recommendations"
      ? state.recommendationVisibleCount < state.recommendationBuffer.length
      : Boolean(state.nextCursor)
  ));
  const isEmpty = computed(() => (
    state.initialized && !state.initialLoading && !state.error && visibleItems.value.length === 0
  ));

  /** Load page one for one route-owned Home selection. */
  async function loadSelection(mode: HomeMode, filters: VideoFilters, force = false): Promise<void> {
    const key = homeSelectionKey(mode, filters);
    if (!force && state.initialized && state.selectionKey === key) return;

    const generation = ++state.requestGeneration;
    state.initialized = true;
    state.selectionKey = key;
    state.mode = mode;
    state.filters = { ...filters };
    state.items = [];
    state.recommendationBuffer = [];
    state.recommendationVisibleCount = 0;
    state.nextCursor = null;
    state.error = "";
    state.nextPageError = "";
    state.initialLoading = true;
    state.loadingMore = false;

    try {
      const payload = await fetchDiscoveryPayload(mode, {
        limit: mode === "recommendations" ? RECOMMENDATION_FETCH_LIMIT : PAGE_SIZE,
        filters
      });
      // A route change can complete while this request is in flight. Old data
      // must never leak into the newly selected feed generation.
      if (generation !== state.requestGeneration) return;

      // TEMP-DISCOVERY-RECOMMENDATIONS: buffer the one-shot finite recommendation batch for local paging; remove when Recommended exposes a native continuation contract.
      if (mode === "recommendations") {
        state.recommendationBuffer = dedupeVideoRows(payload.items ?? []);
        state.recommendationVisibleCount = Math.min(PAGE_SIZE, state.recommendationBuffer.length);
        state.nextCursor = null;
      } else {
        state.items = dedupeVideoRows(payload.items ?? []);
        state.nextCursor = payload.pagination?.has_more
          ? payload.pagination?.next_cursor ?? null
          : null;
      }
    } catch (error) {
      if (generation !== state.requestGeneration) return;
      state.error = errorMessage(error, "Failed to load feed");
      state.nextCursor = null;
    } finally {
      if (generation === state.requestGeneration) state.initialLoading = false;
    }
  }

  /** Load or reveal exactly one continuation window for the active selection. */
  async function loadMore(): Promise<void> {
    if (state.initialLoading || state.loadingMore || state.nextPageError || !canLoadMore.value) return;

    // TEMP-DISCOVERY-RECOMMENDATIONS: reveal the one-shot finite recommendation batch locally; remove when Recommended exposes a native continuation contract.
    if (state.mode === "recommendations") {
      state.recommendationVisibleCount = Math.min(
        state.recommendationVisibleCount + PAGE_SIZE,
        state.recommendationBuffer.length
      );
      return;
    }

    const cursor = state.nextCursor;
    if (!cursor) return;
    const generation = state.requestGeneration;
    const mode = state.mode;
    const filters = { ...state.filters };
    state.loadingMore = true;
    state.nextPageError = "";

    try {
      const payload = await fetchDiscoveryPayload(mode, { limit: PAGE_SIZE, cursor, filters });
      if (generation !== state.requestGeneration) return;
      appendUniqueVideoRows(state.items, payload.items ?? []);
      state.nextCursor = payload.pagination?.has_more
        ? payload.pagination?.next_cursor ?? null
        : null;
    } catch (error) {
      if (generation !== state.requestGeneration) return;
      if (mode === "random" && error instanceof DiscoveryApiError && error.code === "V1_DISCOVERY_STALE_CURSOR") {
        // A rebuilt persisted order invalidates the entire chain. Retrying the
        // old cursor cannot succeed, so restart the same route selection.
        await loadSelection(mode, filters, true);
        return;
      }
      // Ordinary continuation failures are non-destructive. Keeping the cursor
      // makes explicit Retry repeat the same page instead of skipping content.
      state.nextPageError = errorMessage(error, "Failed to load more videos");
    } finally {
      if (generation === state.requestGeneration) state.loadingMore = false;
    }
  }

  /** Retry one ordinary continuation with the unchanged provider cursor. */
  async function retryNextPage(): Promise<void> {
    if (!state.nextPageError) return;
    state.nextPageError = "";
    await loadMore();
  }

  /** Retry/reset page one explicitly without changing the route selection. */
  async function retrySelection(): Promise<void> {
    await loadSelection(state.mode, { ...state.filters }, true);
  }

  return {
    state,
    visibleItems,
    canLoadMore,
    isEmpty,
    loadSelection,
    loadMore,
    retryNextPage,
    retrySelection
  };
}

/** Convert unknown transport failures to one user-facing message. */
function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
