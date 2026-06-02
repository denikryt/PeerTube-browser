<script setup lang="ts">
/** Video detail route backed by Client v1 video metadata and similar APIs. */
import { computed, onMounted, reactive } from "vue";
import { useRoute } from "vue-router";
import StatusBlock from "../components/StatusBlock.vue";
import SimilarVideoCard from "../components/SimilarVideoCard.vue";
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
const channelLabel = computed(() => state.metadata?.channelName || "Unknown channel");
// Preserve the old avatar fallback badges for metadata rows when PeerTube has no image.
const channelInitials = computed(() => {
  const label = channelLabel.value.trim();
  if (!label) return "•";
  const words = label.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
});
// Keep instance/account chips separate from the channel subline to match the legacy detail page hierarchy.
const instanceLabel = computed(() => state.metadata?.instanceName || host.value);
const instanceHref = computed(() => state.metadata?.instanceUrl || (host.value ? `https://${host.value}` : "#"));
const accountLabel = computed(() => state.metadata?.accountName || "");
const subscribersLabel = computed(() => {
  const value = state.metadata?.subscribersCount;
  if (value === null || value === undefined) return "";
  return `${formatStatValue(value)} subscribers`;
});

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
          <div class="channel-avatar" aria-hidden="true">
            <img v-if="state.metadata?.channelAvatarUrl" :src="state.metadata.channelAvatarUrl" alt="" />
            <span v-else>{{ channelInitials }}</span>
          </div>
          <div class="channel-meta">
            <div class="channel-line">
              <p class="video-channel">
                <a v-if="state.metadata?.channelUrl" :href="state.metadata.channelUrl" target="_blank" rel="noreferrer">{{ channelLabel }}</a>
                <span v-else>{{ channelLabel }}</span>
              </p>
              <div class="meta-chips">
                <div v-if="instanceLabel" class="instance-meta">
                  <span class="instance-avatar" :class="{ fallback: !state.metadata?.instanceAvatarUrl }" aria-hidden="true">
                    <img v-if="state.metadata?.instanceAvatarUrl" :src="state.metadata.instanceAvatarUrl" alt="" />
                    <span v-else>{{ instanceLabel.slice(0, 2).toUpperCase() }}</span>
                  </span>
                  <a class="instance-link" :href="instanceHref" target="_blank" rel="noreferrer">{{ instanceLabel }}</a>
                </div>
                <div v-if="accountLabel" class="instance-meta">
                  <span class="instance-avatar" :class="{ fallback: !state.metadata?.accountAvatarUrl }" aria-hidden="true">
                    <img v-if="state.metadata?.accountAvatarUrl" :src="state.metadata.accountAvatarUrl" alt="" />
                    <span v-else>{{ accountLabel.slice(0, 2).toUpperCase() }}</span>
                  </span>
                  <a class="instance-link" :href="state.metadata?.accountUrl || '#'" target="_blank" rel="noreferrer">{{ accountLabel }}</a>
                </div>
              </div>
            </div>
            <div class="channel-subline">
              <span v-if="subscribersLabel" class="channel-subscribers">{{ subscribersLabel }}</span>
              <span v-if="published" class="channel-published">{{ published }}</span>
            </div>
          </div>
        </div>
        <div class="video-meta-row">
          <div class="video-metrics">
            <span class="metric">
              <span v-html="iconEye()"></span>
              <span>{{ formatStatValue(state.metadata?.views) }}</span>
            </span>
          </div>
          <div class="player-actions">
            <button :class="['ghost-button', 'icon-button', { active: state.likeActive }]" type="button" aria-label="Like" @click="like">
              <span v-html="iconThumbUp()"></span>
              <span class="count">{{ formatStatValue(state.metadata?.likes) }}</span>
            </button>
            <button :class="['ghost-button', 'icon-button', { active: state.dislikeActive }]" type="button" aria-label="Dislike" @click="dislike">
              <span v-html="iconThumbDown()"></span>
              <span class="count">{{ formatStatValue(state.metadata?.dislikes) }}</span>
            </button>
            <a v-if="state.metadata?.originalUrl" class="ghost-link" :href="state.metadata.originalUrl" target="_blank" rel="noreferrer">Open original</a>
          </div>
        </div>
        <div class="video-description">{{ state.metadata?.description || "No description available." }}</div>
      </div>
    </section>

    <section id="similar-section" class="similar-card">
      <div class="section-header">
        <h3>Similar videos</h3>
        <RouterLink class="ghost-link" :to="{ name: 'home', query: { id, host } }">Open full list</RouterLink>
      </div>
      <StatusBlock v-if="state.similarLoading" message="Loading similar videos..." />
      <StatusBlock v-else-if="state.similarError" kind="error" :message="state.similarError" />
      <StatusBlock v-else-if="state.similar.length === 0" kind="empty" message="No similar videos found." />
      <div v-else class="similar-grid">
        <SimilarVideoCard v-for="row in state.similar" :key="`${row.instance_domain ?? row.instanceDomain}::${row.video_uuid ?? row.videoUuid ?? row.video_id}`" :row="row" />
      </div>
    </section>
  </main>
</template>
