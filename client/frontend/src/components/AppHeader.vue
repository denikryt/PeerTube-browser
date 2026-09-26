<script setup lang="ts">
/**
 * Shared landing shell navigation for the Vue SPA.
 *
 * Search deliberately routes to the existing Search view, which keeps its
 * separate video and channel providers.  The sidebar only changes route-owned
 * discovery state, so the Home view remains the single owner of feed loading.
 */
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const searchQuery = ref("");
const isVideoDetail = computed(() => route.name === "video-detail");

/** Send both video and channel searching through the existing combined view. */
function submitSearch(): void {
  const q = searchQuery.value.trim();
  void router.push({ name: "search", query: q ? { q } : {} });
}

</script>

<template>
  <aside v-if="!isVideoDetail" class="app-sidebar">
    <RouterLink class="brand" to="/" aria-label="PeerTube Browser home">
      <img class="brand-mark" src="/favicon.png" alt="" aria-hidden="true" />
      <span>PeerTube Browser</span>
    </RouterLink>

    <nav class="sidebar-nav" aria-label="Browse videos">
      <RouterLink class="sidebar-link" :to="{ name: 'home' }">Home</RouterLink>
      <RouterLink class="sidebar-link" :to="{ name: 'home', query: { mode: 'fresh' } }">Fresh</RouterLink>
      <RouterLink class="sidebar-link" :to="{ name: 'home', query: { mode: 'trending' } }">Trending</RouterLink>
      <RouterLink class="sidebar-link" :to="{ name: 'categories' }">Categories</RouterLink>
      <RouterLink class="sidebar-link" :to="{ name: 'tags' }">Tags</RouterLink>
      <RouterLink class="sidebar-link" :to="{ name: 'channels' }">Channels</RouterLink>
    </nav>
  </aside>

  <header v-if="!isVideoDetail" class="landing-header">
    <form class="landing-search" role="search" @submit.prevent="submitSearch">
      <label class="sr-only" for="global-search">Search videos and channels</label>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21 21-4.4-4.4m1.4-5.1a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z" /></svg>
      <input id="global-search" v-model="searchQuery" type="search" autocomplete="off" placeholder="Search videos, channels, topics…" />
      <button type="submit">Search</button>
    </form>
  </header>
  <header v-else class="videos-header">
    <div><p class="eyebrow">PeerTube videos</p></div>
    <nav class="header-nav" aria-label="Video navigation">
      <RouterLink class="nav-link" to="/">Home</RouterLink>
      <a class="nav-link" href="#similar-section">Similar videos</a>
    </nav>
  </header>
</template>
