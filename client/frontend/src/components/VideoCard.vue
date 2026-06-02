<script setup lang="ts">
/**
 * Shared YouTube-style video card for Home and Search result grids.
 *
 * This component intentionally owns the feed/search card structure. Similar
 * videos on the detail page use a separate compact component, but Home and
 * Search must stay visually identical and must not reintroduce reaction/action
 * rows that belong to the video-detail surface.
 */
import { computed } from "vue";
import type { VideoRow } from "../types/videos";
import { formatDuration, formatStatValue, formatTimeAgo, normalizeStatValue } from "../utils/format";
import { channelAvatarUrl, channelInitials, channelName, channelUrl, hasServerStats, publishedAtMs, thumbnailUrl, videoPageUrl } from "../utils/video-fields";

const props = defineProps<{ row: VideoRow }>();
const title = computed(() => props.row.title ?? "Untitled video");
const thumb = computed(() => thumbnailUrl(props.row));
const duration = computed(() => formatDuration(props.row.duration ?? null));
const channelLabel = computed(() => channelName(props.row) || "Unknown channel");
const channelHref = computed(() => channelUrl(props.row));
const avatar = computed(() => channelAvatarUrl(props.row));
const initials = computed(() => channelInitials(props.row));
const detailUrl = computed(() => videoPageUrl(props.row));
const published = computed(() => {
  const value = publishedAtMs(props.row);
  return value ? formatTimeAgo(value) : "";
});
const views = computed(() => {
  if (!hasServerStats(props.row)) return null;
  return normalizeStatValue(props.row.views ?? props.row.viewsCount);
});
const metaLine = computed(() => {
  const parts = [`${formatStatValue(views.value)} views`];
  if (published.value) parts.push(published.value);
  return parts.join(" · ");
});
</script>

<template>
  <article class="video-card">
    <RouterLink class="video-card-thumbnail-link" :to="detailUrl" :aria-label="title">
      <div class="video-thumb">
        <img v-if="thumb" :src="thumb" :alt="title" loading="lazy" />
        <div v-else class="thumb-fallback">{{ title }}</div>
        <span class="duration">{{ duration }}</span>
      </div>
    </RouterLink>

    <div class="video-card-meta">
      <a class="channel-avatar" :href="channelHref" target="_blank" rel="noreferrer" :aria-label="channelLabel">
        <img v-if="avatar" :src="avatar" alt="" loading="lazy" />
        <span v-else>{{ initials }}</span>
      </a>
      <div class="video-card-text">
        <RouterLink class="video-title-link" :to="detailUrl">
          <h3 class="video-title">{{ title }}</h3>
        </RouterLink>
        <a class="channel-link" :href="channelHref" target="_blank" rel="noreferrer">
          {{ channelLabel }}
        </a>
        <div class="video-meta">{{ metaLine }}</div>
      </div>
      <button class="video-card-menu" type="button" aria-label="More options" title="More options">
        <span aria-hidden="true">⋮</span>
      </button>
    </div>
  </article>
</template>
