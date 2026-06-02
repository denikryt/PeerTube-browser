<script setup lang="ts">
/** Home feed route for recommendations and random discovery. */
import { computed, onMounted, ref } from "vue";
import VideoCard from "../components/VideoCard.vue";
import StatusBlock from "../components/StatusBlock.vue";
import { useFeed } from "../composables/useFeed";
import { clearLocalLikes } from "../data/local-likes";
import { fetchUserProfileLikes, resetUserProfileLikes } from "../data/user-profile";
import type { VideoRow } from "../types/videos";

const { state, isEmpty, load } = useFeed();
const profileOpen = ref(false);
const profileLoading = ref(false);
const profileError = ref("");
const likes = ref<VideoRow[]>([]);
const summary = computed(() => state.loading ? "Loading..." : state.rows.length ? `Showing ${state.rows.length} videos` : "");

onMounted(() => void load("recommendations"));

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

async function resetProfile() {
  clearLocalLikes();
  await resetUserProfileLikes(window.location.origin);
  await load(state.mode);
}
</script>

<template>
  <main class="videos-main">
    <section class="summary">
      <div>
        <div>{{ summary }}</div>
        <div class="summary-meta">{{ state.mode === "random" ? "Random discovery" : "Recommendations" }}</div>
      </div>
      <div class="summary-actions">
        <button class="ghost-button" type="button" @click="resetProfile">Reset likes</button>
        <button class="ghost-button" type="button" @click="showLikes">My likes</button>
        <button class="ghost-button" type="button" @click="load('recommendations')">Recommendations</button>
        <button class="ghost-button" type="button" @click="load('random')">Random</button>
      </div>
    </section>

    <StatusBlock v-if="state.loading" kind="loading" message="Loading..." />
    <StatusBlock v-else-if="state.error" kind="error" :message="state.error" />
    <StatusBlock v-else-if="isEmpty" kind="empty" message="No videos found" />
    <section v-else class="cards-grid">
      <VideoCard v-for="row in state.rows" :key="`${row.instance_domain ?? row.instanceDomain}::${row.video_uuid ?? row.videoUuid ?? row.video_id}`" :row="row" />
    </section>

    <button v-if="state.nextCursor && !state.loading" class="ghost-button" type="button" @click="load(state.mode, state.nextCursor)">Load more</button>

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
          <VideoCard v-for="row in likes" v-else :key="`${row.instance_domain ?? row.instanceDomain}::${row.video_uuid ?? row.videoUuid ?? row.video_id}`" :row="row" />
        </div>
      </div>
    </div>
  </main>
</template>
