<script setup lang="ts">
/**
 * Compact similar-video card for the video detail route.
 *
 * The markup intentionally preserves the pre-Vue `similar-card-item` class
 * contract so the detail page keeps its denser related-video layout instead
 * of inheriting full feed-card dimensions.
 */
import { computed } from "vue";
import type { VideoRow } from "../types/videos";
import { formatDuration, formatStatValue, formatTimeAgo, normalizeStatValue } from "../utils/format";
import { channelName, publishedAtMs, thumbnailUrl, videoPageUrl } from "../utils/video-fields";

const props = defineProps<{ row: VideoRow }>();
const title = computed(() => props.row.title ?? "Untitled video");
const thumb = computed(() => thumbnailUrl(props.row));
const duration = computed(() => formatDuration(props.row.duration ?? null));
const channel = computed(() => channelName(props.row) || "Unknown channel");
const views = computed(() => normalizeStatValue(props.row.views ?? props.row.viewsCount));
const published = computed(() => {
  const value = publishedAtMs(props.row);
  return value ? ` · ${formatTimeAgo(value)}` : "";
});
const detailUrl = computed(() => videoPageUrl(props.row));
</script>

<template>
  <RouterLink class="similar-card-item" :to="detailUrl">
    <div class="similar-thumb">
      <img v-if="thumb" :src="thumb" :alt="title" loading="lazy" />
      <span class="duration">{{ duration }}</span>
    </div>
    <h4 class="similar-title">{{ title }}</h4>
    <p class="similar-channel">{{ channel }}</p>
    <p class="similar-meta"><span data-stat="views">{{ formatStatValue(views) }}</span> views{{ published }}</p>
  </RouterLink>
</template>
