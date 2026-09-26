<script setup lang="ts">
/** Home content browser with route-owned mode/filters and cached feed state. */
import {
  computed,
  nextTick,
  onActivated,
  onDeactivated,
  onUnmounted,
  ref,
  watch
} from "vue";
import { useRoute, useRouter } from "vue-router";
import VideoCard from "../components/VideoCard.vue";
import VideoFilterControls from "../components/VideoFilterControls.vue";
import StatusBlock from "../components/StatusBlock.vue";
import { useFeed } from "../composables/useFeed";
import { clearLocalLikes } from "../data/local-likes";
import { fetchUserProfileLikes, resetUserProfileLikes } from "../data/user-profile";
import {
  homeSelectionKey,
  parseHomeMode,
  parseVideoFilterQuery,
  serializeHomeMode,
  serializeVideoFilters,
  type HomeMode
} from "../state/video-filters";
import type { VideoFilters } from "../types/video-filters";
import type { VideoRow } from "../types/videos";
import { videoRowKey } from "../utils/video-fields";

const route = useRoute();
const router = useRouter();
const feed = useFeed();
const { state, visibleItems, canLoadMore, isEmpty, loadSelection, loadMore, retryNextPage, retrySelection } = feed;

const profileOpen = ref(false);
const profileLoading = ref(false);
const profileError = ref("");
const likes = ref<VideoRow[]>([]);
const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;
let active = false;

const mode = computed(() => parseHomeMode(route.query.mode));
const filters = computed(() => parseVideoFilterQuery(route.query as Record<string, unknown>));
const routeSelectionKey = computed(() => homeSelectionKey(mode.value, filters.value));
const summary = computed(() => state.initialLoading
  ? "Loading..."
  : visibleItems.value.length
    ? `Showing ${visibleItems.value.length} videos`
    : "");
const modeLabel = computed(() => ({
  recommendations: "Recommended",
  fresh: "Fresh",
  popular: "Popular",
  random: "Random"
})[mode.value]);

/** Ensure the cached Home instance reflects the current route selection. */
async function ensureRouteSelection() {
  if (route.name !== "home") return;
  await loadSelection(mode.value, filters.value);
}

/** Replace route-owned selection controls without creating browser-history noise. */
function replaceSelection(nextMode: HomeMode, nextFilters: VideoFilters) {
  void router.replace({
    name: "home",
    query: { ...serializeHomeMode(nextMode), ...serializeVideoFilters(nextFilters) }
  });
}

function setMode(nextMode: HomeMode) {
  replaceSelection(nextMode, filters.value);
}

/** Apply one complete shared-filter selection while keeping Home URL-owned. */
function setFilters(nextFilters: VideoFilters) {
  replaceSelection(mode.value, nextFilters);
}

/** Observer owns only viewport triggering; provider cursor state stays in useFeed. */
function connectObserver() {
  disconnectObserver();
  if (!active || !sentinel.value || !canLoadMore.value || state.nextPageError || state.initialLoading) return;
  observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) void loadMore();
  }, { rootMargin: "240px 0px" });
  observer.observe(sentinel.value);
}

function disconnectObserver() {
  observer?.disconnect();
  observer = null;
}

async function showLikes() {
  profileOpen.value = true;
  profileLoading.value = true;
  profileError.value = "";
  try {
    likes.value = await fetchUserProfileLikes(window.location.origin);
  } catch (error) {
    profileError.value = error instanceof Error ? error.message : "Failed to load likes";
  } finally {
    profileLoading.value = false;
  }
}

/** Profile reset invalidates only the recommendation input, not unrelated feeds. */
async function resetProfile() {
  clearLocalLikes();
  await resetUserProfileLikes(window.location.origin);
  if (state.mode === "recommendations") {
    await loadSelection(state.mode, { ...state.filters }, true);
  }
}

watch(
  () => [route.name, routeSelectionKey.value] as const,
  () => void ensureRouteSelection(),
  { immediate: true }
);
watch(
  () => [canLoadMore.value, state.nextPageError, state.initialLoading, state.loadingMore, sentinel.value] as const,
  () => void nextTick(connectObserver)
);

onActivated(() => {
  active = true;
  void ensureRouteSelection().then(() => nextTick(connectObserver));
});
onDeactivated(() => {
  active = false;
  disconnectObserver();
});
onUnmounted(() => {
  active = false;
  disconnectObserver();
});
</script>

<template>
  <main class="videos-main">
    <section class="summary">
      <div>
        <div>{{ summary }}</div>
        <div class="summary-meta">{{ modeLabel }} discovery</div>
      </div>
      <div class="summary-actions">
        <button class="ghost-button" type="button" @click="resetProfile">Reset likes</button>
        <button class="ghost-button" type="button" @click="showLikes">My likes</button>
      </div>
    </section>

    <nav class="discovery-modes" aria-label="Discovery mode">
      <button
        v-for="candidate in (['recommendations', 'fresh', 'popular', 'random'] as HomeMode[])"
        :key="candidate"
        class="mode-button"
        :class="{ active: mode === candidate }"
        type="button"
        @click="setMode(candidate)"
      >
        {{ candidate === 'recommendations' ? 'Recommended' : candidate[0].toUpperCase() + candidate.slice(1) }}
      </button>
    </nav>

    <VideoFilterControls :filters="filters" @change="setFilters" />

    <StatusBlock v-if="state.initialLoading" kind="loading" message="Loading..." />
    <div v-else-if="state.error" class="continuation-error">
      <StatusBlock kind="error" :message="state.error" />
      <button class="ghost-button" type="button" @click="retrySelection">Retry</button>
    </div>
    <StatusBlock v-else-if="isEmpty" kind="empty" message="No videos found" />
    <section v-else class="cards-grid">
      <VideoCard
        v-for="row in visibleItems"
        :key="videoRowKey(row)"
        :row="row"
      />
    </section>

    <div v-if="state.nextPageError" class="continuation-error" role="status">
      <span>{{ state.nextPageError }}</span>
      <button class="ghost-button" type="button" @click="retryNextPage">Retry</button>
    </div>
    <div v-if="state.loadingMore" class="loading">Loading more…</div>
    <div v-if="canLoadMore && !state.nextPageError" ref="sentinel" class="feed-sentinel" aria-hidden="true"></div>

    <div v-if="profileOpen" class="modal">
      <div class="modal-backdrop" @click="profileOpen = false"></div>
      <div class="modal-content" role="dialog" aria-modal="true" aria-labelledby="profile-modal-title">
        <header class="modal-header">
          <h2 id="profile-modal-title">User likes</h2>
          <button class="ghost-button" type="button" @click="profileOpen = false">Close</button>
        </header>
        <p class="modal-subtitle">Most recent likes.</p>
        <div class="modal-body likes-grid" tabindex="0">
          <StatusBlock v-if="profileLoading" message="Loading likes..." />
          <StatusBlock v-else-if="profileError" kind="error" :message="profileError" />
          <StatusBlock v-else-if="likes.length === 0" kind="empty" message="No likes stored yet." />
          <template v-else>
            <VideoCard
              v-for="row in likes"
              :key="videoRowKey(row)"
              :row="row"
            />
          </template>
        </div>
      </div>
    </div>
  </main>
</template>
