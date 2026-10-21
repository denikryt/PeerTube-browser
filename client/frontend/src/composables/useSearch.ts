/** Stateful Search v1 loader for videos and channels. */
import { reactive } from "vue";
import { fetchChannelSearchPayload, fetchVideoSearchPayload } from "../data/search";
import type { ChannelRow } from "../types/channels";
import type { VideoRow } from "../types/videos";

/** Create Search API v1 state and actions with independent error slots. */
export function useSearch() {
  const state = reactive({
    q: "",
    videos: [] as VideoRow[],
    channels: [] as ChannelRow[],
    loadingVideos: false,
    loadingChannels: false,
    videoError: "",
    channelError: ""
  });

  async function search(query: string) {
    const q = query.trim();
    state.q = q;
    state.videos = [];
    state.channels = [];
    state.videoError = "";
    state.channelError = "";
    if (!q) return;

    state.loadingVideos = true;
    state.loadingChannels = true;
    const [videoResult, channelResult] = await Promise.allSettled([
      fetchVideoSearchPayload({ q, limit: 20 }),
      fetchChannelSearchPayload({ q, limit: 20 })
    ]);

    if (videoResult.status === "fulfilled") {
      state.videos = videoResult.value.items ?? [];
    } else {
      state.videoError = videoResult.reason instanceof Error ? videoResult.reason.message : "Video search failed";
    }
    if (channelResult.status === "fulfilled") {
      state.channels = channelResult.value.items ?? [];
    } else {
      state.channelError = channelResult.reason instanceof Error ? channelResult.reason.message : "Channel search failed";
    }
    state.loadingVideos = false;
    state.loadingChannels = false;
  }

  return { state, search };
}
