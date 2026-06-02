/** Stateful channel-browser loader for the Vue Channels route. */
import { reactive } from "vue";
import { fetchChannelsPayload } from "../data/channels";
import type { ChannelRow } from "../types/channels";

export type ChannelSortKey = "name" | "instance" | "videos" | "followers" | "checked";
export type ChannelSortDir = "asc" | "desc";

/** Create channel browser filter, sort, pagination, and loading state. */
export function useChannels() {
  const state = reactive({
    rows: [] as ChannelRow[],
    total: 0,
    page: 1,
    pageSize: 100,
    q: "",
    instance: "",
    minFollowers: 0,
    minVideos: 0,
    maxVideos: null as number | null,
    sort: "followers" as ChannelSortKey,
    dir: "desc" as ChannelSortDir,
    loading: false,
    error: "",
    generatedAt: null as number | null
  });

  async function load() {
    state.loading = true;
    state.error = "";
    try {
      const payload = await fetchChannelsPayload({
        limit: state.pageSize,
        offset: (state.page - 1) * state.pageSize,
        q: state.q,
        instance: state.instance,
        minFollowers: state.minFollowers,
        minVideos: state.minVideos,
        maxVideos: state.maxVideos,
        sort: state.sort,
        dir: state.dir
      });
      const rows = Array.isArray(payload) ? payload : payload.rows ?? [];
      state.rows = rows;
      state.total = Array.isArray(payload) ? rows.length : payload.total ?? rows.length;
      state.generatedAt = Array.isArray(payload) ? null : payload.generatedAt ?? null;
    } catch (error) {
      state.rows = [];
      state.total = 0;
      state.error = error instanceof Error ? error.message : "Failed to load channels";
    } finally {
      state.loading = false;
    }
  }

  function toggleSort(key: ChannelSortKey) {
    if (state.sort === key) {
      state.dir = state.dir === "asc" ? "desc" : "asc";
    } else {
      state.sort = key;
      state.dir = key === "name" || key === "instance" ? "asc" : "desc";
    }
    state.page = 1;
  }

  return { state, load, toggleSort };
}
