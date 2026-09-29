<script setup lang="ts">
/**
 * Shared YouTube-style video card for Home and Search result grids.
 *
 * This component intentionally owns the feed/search card structure. Similar
 * videos on the detail page use a separate compact component. Home and Search
 * preserve the familiar thumbnail/avatar/title/channel/meta hierarchy and
 * expose only the positive reaction count in the dense feed context.
 */
import { computed } from "vue";
import type { VideoRow } from "../types/videos";
import { iconPlayOutline, iconThumbUp } from "./icons";
import { formatCompactStatValue, formatDuration, formatTimeAgo, normalizeStatValue } from "../utils/format";
import { channelAvatarUrl, channelInitials, channelName, channelUrl, hasServerStats, publishedAtMs, resolveInstanceDomain, thumbnailCandidates, videoPageUrl } from "../utils/video-fields";
import VideoThumbnail from "./VideoThumbnail.vue";

const props = defineProps<{ row: VideoRow }>();
const title = computed(() => props.row.title ?? "Untitled video");
const thumbs = computed(() => thumbnailCandidates(props.row));
const duration = computed(() => formatDuration(props.row.duration ?? null));
const channelLabel = computed(() => channelName(props.row) || "Unknown channel");
// Keep the host visible with its channel, rather than mixing provenance into stats.
const instanceDomain = computed(() => resolveInstanceDomain(props.row));
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
const likes = computed(() => {
  if (!hasServerStats(props.row)) return null;
  return normalizeStatValue(props.row.likes ?? props.row.likes_count);
});
const compactViews = computed(() => formatCompactStatValue(views.value));
</script>

<template>
  <article class="video-card">
    <RouterLink class="video-card-thumbnail-link" :to="detailUrl" :aria-label="title">
      <div class="video-thumb">
        <VideoThumbnail :candidates="thumbs" :alt="title" />
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
        <div class="channel-line">
          <a class="channel-link" :href="channelHref" target="_blank" rel="noreferrer">
            {{ channelLabel }}
          </a>
          <span v-if="instanceDomain" class="channel-instance"><span class="channel-instance-host">{{ instanceDomain }}</span></span>
        </div>
        <div class="video-meta">
          <span class="video-meta-views"><span v-html="iconPlayOutline()"></span>{{ compactViews }}</span>
          <span class="video-card-likes" aria-label="Likes"><span v-html="iconThumbUp()"></span>{{ formatCompactStatValue(likes) }}</span>
          <span v-if="published" class="video-meta-time"> · {{ published }}</span>
        </div>
      </div>
      <button class="video-card-menu" type="button" aria-label="More options" title="More options">
        <span aria-hidden="true">⋮</span>
      </button>
    </div>
  </article>
</template>
