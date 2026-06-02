<script setup lang="ts">
/** Video detail route backed by Client v1 video metadata and similar APIs. */
import { computed, onMounted, reactive } from "vue";
import { useRoute } from "vue-router";
import StatusBlock from "../components/StatusBlock.vue";
import VideoCard from "../components/VideoCard.vue";
import { fetchVideoMetadataPayload, type VideoMetadata } from "../data/video-detail";
import { fetchSimilarVideosPayload } from "../data/videos";
import { addLocalLike } from "../data/local-likes";
import { sendUserAction } from "../data/user-actions";
import type { VideoRow } from "../types/videos";
import { iconEye, iconThumbDown, iconThumbUp } from "../components/icons";
import { formatStatValue, formatTimeAgo } from "../utils/format";

const route = useRoute();
const state = reactive({
  metadata: null as VideoMetadata | null,
  similar: [] as VideoRow[],
  loading: false,
  similarLoading: false,
  error: "",
  similarError: "",
  likeActive: false,
  dislikeActive: false
});
const host = computed(() => String(route.params.host ?? ""));
const id = computed(() => String(route.params.id ?? ""));
const title = computed(() => state.metadata?.title ?? "Video");
const published = computed(() => state.metadata?.publishedAt ? formatTimeAgo(state.metadata.publishedAt) : "");

onMounted(async () => {
  await loadVideo();
  await loadSimilar();
});

async function loadVideo() {
  if (!host.value || !id.value) {
    state.error = "Missing video identity";
    return;
  }
  state.loading = true;
  state.error = "";
  try {
    state.metadata = await fetchVideoMetadataPayload({ id: id.value, host: host.value });
    document.title = `${state.metadata.title ?? "Video"} - PeerTube - Browser`;
  } catch (error) {
    state.error = error instanceof Error ? error.message : "Failed to load video";
  } finally {
    state.loading = false;
  }
}

async function loadSimilar() {
  state.similarLoading = true;
  state.similarError = "";
  try {
    const payload = await fetchSimilarVideosPayload({ id: id.value, host: host.value, limit: "8" });
    state.similar = payload.rows ?? payload.items ?? [];
  } catch (error) {
    state.similarError = error instanceof Error ? error.message : "Failed to load similar videos";
  } finally {
    state.similarLoading = false;
  }
}

async function like() {
  state.likeActive = !state.likeActive;
  if (state.likeActive) state.dislikeActive = false;
  try {
    await sendUserAction(window.location.origin, { videoId: id.value, host: host.value, action: "like" });
  } catch {
    // Local like persistence is still useful when the action endpoint is unavailable.
  } finally {
    const uuid = state.metadata?.videoUuid || id.value;
    if (uuid && host.value) addLocalLike(uuid, host.value);
  }
}

function dislike() {
  state.dislikeActive = !state.dislikeActive;
  if (state.dislikeActive) state.likeActive = false;
}
</script>

<template>
  <main class="video-main">
    <StatusBlock v-if="state.loading" message="Loading video..." />
    <StatusBlock v-else-if="state.error" kind="error" :message="state.error" />
    <section v-else class="player-card">
      <div class="player-frame">
        <iframe v-if="state.metadata?.embedUrl" :src="state.metadata.embedUrl" allowfullscreen title="PeerTube video"></iframe>
      </div>
      <div class="player-info">
        <h2 class="video-title">{{ title }}</h2>
        <div class="channel-row">
          <div class="channel-avatar"><img v-if="state.metadata?.channelAvatarUrl" :src="state.metadata.channelAvatarUrl" alt="" /><span v-else>•</span></div>
          <div class="channel-meta">
            <p class="video-channel"><a v-if="state.metadata?.channelUrl" :href="state.metadata.channelUrl" target="_blank" rel="noreferrer">{{ state.metadata.channelName }}</a><span v-else>{{ state.metadata?.channelName }}</span></p>
            <div class="video-meta">{{ state.metadata?.instanceName || host }} <span v-if="published">· {{ published }}</span></div>
          </div>
        </div>
        <div class="metrics-row">
          <span class="metric" v-html="iconEye()"></span><span>{{ formatStatValue(state.metadata?.views) }}</span>
          <button :class="['reaction-button', { active: state.likeActive }]" type="button" @click="like"><span v-html="iconThumbUp()"></span>{{ formatStatValue(state.metadata?.likes) }}</button>
          <button :class="['reaction-button', { active: state.dislikeActive }]" type="button" @click="dislike"><span v-html="iconThumbDown()"></span>{{ formatStatValue(state.metadata?.dislikes) }}</button>
        </div>
        <p class="video-description">{{ state.metadata?.description || "No description available." }}</p>
        <a v-if="state.metadata?.originalUrl" class="ghost-link" :href="state.metadata.originalUrl" target="_blank" rel="noreferrer">Open original video</a>
      </div>
    </section>

    <section class="similar-card">
      <h2>Similar videos</h2>
      <StatusBlock v-if="state.similarLoading" message="Loading similar videos..." />
      <StatusBlock v-else-if="state.similarError" kind="error" :message="state.similarError" />
      <StatusBlock v-else-if="state.similar.length === 0" kind="empty" message="No similar videos found." />
      <div v-else class="cards-grid">
        <VideoCard v-for="row in state.similar" :key="`${row.instance_domain ?? row.instanceDomain}::${row.video_uuid ?? row.videoUuid ?? row.video_id}`" :row="row" />
      </div>
    </section>
  </main>
</template>
