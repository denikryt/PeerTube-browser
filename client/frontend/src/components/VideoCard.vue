<script setup lang="ts">
/**
 * Vue video-card renderer for feed, search, and similar results.
 *
 * The component keeps the existing CSS class contract but builds canonical
 * Vue Router links instead of legacy HTML query-string detail URLs.
 */
import { computed } from "vue";
import type { VideoRow } from "../types/videos";
import { formatDuration, formatStatValue, formatTimeAgo, normalizeStatValue } from "../utils/format";
import { channelAvatarUrl, channelInitials, channelName, channelUrl, hasServerStats, publishedAtMs, thumbnailUrl, videoPageUrl } from "../utils/video-fields";
import { iconThumbDown, iconThumbUp } from "./icons";

const props = defineProps<{ row: VideoRow; compact?: boolean }>();
const title = computed(() => props.row.title ?? "Untitled video");
const thumb = computed(() => thumbnailUrl(props.row));
const duration = computed(() => formatDuration(props.row.duration ?? null));
const channelLabel = computed(() => channelName(props.row) || "Unknown channel");
const channelHref = computed(() => channelUrl(props.row));
const avatar = computed(() => channelAvatarUrl(props.row));
const initials = computed(() => channelInitials(props.row));
const published = computed(() => {
  const value = publishedAtMs(props.row);
  return value ? ` · ${formatTimeAgo(value)}` : "";
});
const stats = computed(() => {
  if (!hasServerStats(props.row)) return { views: null, likes: null, dislikes: null };
  return {
    views: normalizeStatValue(props.row.views ?? props.row.viewsCount),
    likes: normalizeStatValue(props.row.likes ?? props.row.likes_count),
    dislikes: normalizeStatValue(props.row.dislikes ?? props.row.dislikes_count)
  };
});
const detailUrl = computed(() => videoPageUrl(props.row));
</script>

<template>
  <article class="video-card">
    <RouterLink class="video-link" :to="detailUrl">
      <div class="video-thumb">
        <img v-if="thumb" :src="thumb" :alt="title" loading="lazy" />
        <div v-else class="thumb-fallback">No preview</div>
        <span class="duration">{{ duration }}</span>
      </div>
      <div class="video-body">
        <h3 class="video-title">{{ title }}</h3>
        <div class="video-footer">
          <div class="channel-meta">
            <div class="channel-avatar" aria-hidden="true">
              <img v-if="avatar" :src="avatar" alt="" loading="lazy" />
              <span v-else>{{ initials }}</span>
            </div>
            <div class="channel-text">
              <a class="channel-link" :href="channelHref" target="_blank" rel="noreferrer" @click.stop>
                {{ channelLabel }}
              </a>
              <div class="video-meta"><span data-stat="views">{{ formatStatValue(stats.views) }}</span> views{{ published }}</div>
            </div>
          </div>
          <div class="video-stats">
            <span class="stat likes" v-html="iconThumbUp()"></span><span data-stat="likes">{{ formatStatValue(stats.likes) }}</span>
            <span class="stat dislikes" v-html="iconThumbDown()"></span><span data-stat="dislikes">{{ formatStatValue(stats.dislikes) }}</span>
          </div>
        </div>
      </div>
    </RouterLink>
  </article>
</template>
