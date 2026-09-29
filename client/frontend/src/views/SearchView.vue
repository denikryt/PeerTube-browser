<script setup lang="ts">
/** Search page with route-owned video filters and cursor continuation. */
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import ChannelResultRow from "../components/ChannelResultRow.vue";
import StatusBlock from "../components/StatusBlock.vue";
import VideoCard from "../components/VideoCard.vue";
import VideoCardSkeleton from "../components/VideoCardSkeleton.vue";
import VideoFilterControls from "../components/VideoFilterControls.vue";
import { useSearch } from "../composables/useSearch";
import { parseVideoFilterQuery, searchSelectionKey, serializeVideoFilters } from "../state/video-filters";
import type { VideoFilters } from "../types/video-filters";
import { videoRowKey } from "../utils/video-fields";

const route = useRoute();
const router = useRouter();
const input = ref(String(route.query.q ?? ""));
const { state, canLoadMore, search, loadMore, retryNextPage } = useSearch();
const filters = computed(() => parseVideoFilterQuery(route.query as Record<string, unknown>));
const routeQuery = computed(() => String(route.query.q ?? "").trim());
const routeSelectionKey = computed(() => searchSelectionKey(routeQuery.value, filters.value));
const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

function replaceRoute(q: string, nextFilters: VideoFilters) {
  void router.replace({
    name: "search",
    query: { ...(q.trim() ? { q: q.trim() } : {}), ...serializeVideoFilters(nextFilters) }
  });
}

function submit() {
  replaceRoute(input.value, filters.value);
}

function clear() {
  input.value = "";
  replaceRoute("", filters.value);
}

/** Apply one complete shared-filter selection while keeping Search URL-owned. */
function setFilters(nextFilters: VideoFilters) {
  replaceRoute(routeQuery.value, nextFilters);
}

/** The observer triggers only the composable continuation operation. */
function connectObserver() {
  disconnectObserver();
  if (!sentinel.value || !canLoadMore.value || state.nextPageError || state.loadingMore || state.loadingVideos) return;
  observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) void loadMore();
  }, { rootMargin: "240px 0px" });
  observer.observe(sentinel.value);
}

function disconnectObserver() {
  observer?.disconnect();
  observer = null;
}

onUnmounted(disconnectObserver);
watch(routeSelectionKey, () => {
  input.value = routeQuery.value;
  void search(routeQuery.value, filters.value);
}, { immediate: true });
watch(
  () => [canLoadMore.value, state.nextPageError, state.loadingMore, state.loadingVideos, sentinel.value] as const,
  () => void nextTick(connectObserver)
);
</script>

<template>
  <main class="videos-main">
    <form class="search-bar" role="search" @submit.prevent="submit">
      <label class="search-label" for="search-input">Search videos and channels</label>
      <div class="search-controls">
        <input id="search-input" v-model="input" type="search" autocomplete="off" placeholder="Search videos and channels" />
        <button class="search-button" type="submit">Search</button>
        <button v-if="input" class="ghost-button" type="button" @click="clear">Clear</button>
      </div>
    </form>

    <VideoFilterControls :filters="filters" @change="setFilters" />

    <section v-if="!state.q" class="search-landing" aria-label="Search videos">
      <h2>Search videos</h2>
      <p>Use the search box above to find videos by title, channel, tag, category, or instance.</p>
    </section>

    <section v-else class="search-results">
      <div class="search-results-heading">Search results for “{{ state.q }}”</div>
      <section class="search-section">
        <h2>Videos</h2>
        <div v-if="state.loadingVideos" class="cards-grid cards-grid-skeleton" aria-busy="true" aria-label="Searching videos">
          <VideoCardSkeleton v-for="index in 8" :key="index" />
        </div>
        <StatusBlock v-else-if="state.videoError" kind="error" :message="state.videoError" />
        <StatusBlock v-else-if="state.videos.length === 0" kind="empty" message="No videos found" />
        <div v-else class="cards-grid">
          <VideoCard v-for="row in state.videos" :key="videoRowKey(row)" :row="row" />
        </div>
        <div v-if="state.nextPageError" class="continuation-error" role="status">
          <span>{{ state.nextPageError }}</span>
          <button class="ghost-button" type="button" @click="retryNextPage">Retry</button>
        </div>
        <div v-if="state.loadingMore" class="cards-grid cards-grid-skeleton" aria-busy="true" aria-label="Loading more videos">
          <VideoCardSkeleton v-for="index in 4" :key="index" />
        </div>
        <div v-if="canLoadMore && !state.nextPageError" ref="sentinel" class="feed-sentinel" aria-hidden="true"></div>
      </section>
      <section class="search-section">
        <h2>Channels</h2>
        <StatusBlock v-if="state.loadingChannels" message="Searching channels..." />
        <StatusBlock v-else-if="state.channelError" kind="error" :message="state.channelError" />
        <StatusBlock v-else-if="state.channels.length === 0" kind="empty" message="No channels found" />
        <div v-else class="channel-results-list">
          <ChannelResultRow v-for="row in state.channels" :key="`${row.instance_domain}::${row.channel_id}`" :row="row" />
        </div>
      </section>
    </section>
  </main>
</template>
