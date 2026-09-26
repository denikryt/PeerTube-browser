<script setup lang="ts">
/**
 * Shared YouTube-style video card for Home and Search result grids.
 *
 * This component intentionally owns the feed/search card structure. Similar
 * videos on the detail page use a separate compact component, while Home and
 * Search share the same lightweight reaction-count footer.
 */
import { computed, ref } from "vue";
import type { VideoRow } from "../types/videos";
import { iconThumbDown, iconThumbUp } from "./icons";
import { formatDuration, formatStatValue, formatTimeAgo, normalizeStatValue } from "../utils/format";
import { channelAvatarUrl, channelInitials, channelName, channelUrl, hasServerStats, publishedAtMs, thumbnailUrl, videoPageUrl } from "../utils/video-fields";

const props = defineProps<{ row: VideoRow }>();
const title = computed(() => props.row.title ?? "Untitled video");
const thumb = computed(() => thumbnailUrl(props.row));
const thumbErrored = ref(false);
const duration = computed(() => formatDuration(props.row.duration ?? null));
const channelLabel = computed(() => channelName(props.row) || "Unknown channel");
const channelHref = computed(() => channelUrl(props.row));
const avatar = computed(() => channelAvatarUrl(props.row));
const initials = computed(() => channelInitials(props.row));
const detailUrl = computed(() => videoPageUrl(props.row));

const instanceLabel = computed(() => props.row.instance_domain ?? props.row.instanceDomain ?? "");
const languageLabel = computed(() => {
  const raw = props.row.language_label ?? props.row.languageLabel ?? props.row.language ?? null;
  const normalized = typeof raw === "string" ? raw.trim() : "";
  return normalized && normalized !== "_unknown" ? normalized : "";
});
const categoryLabel = computed(() => typeof props.row.category === "string" ? props.row.category.trim() : "");
const published = computed(() => {
  const value = publishedAtMs(props.row);
  return value ? formatTimeAgo(value) : "";
});
const views = computed(() => {
  if (!hasServerStats(props.row)) return null;
  return normalizeStatValue(props.row.views ?? props.row.viewsCount);
});
const likes = computed(() => normalizeStatValue(props.row.likes ?? props.row.likes_count));
const dislikes = computed(() => normalizeStatValue(props.row.dislikes ?? props.row.dislikes_count));
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
        <img v-if="thumb && !thumbErrored" :src="thumb" :alt="title" loading="lazy" @error="thumbErrored = true" />
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
        <div class="video-meta">
          <span>{{ metaLine }}</span>
          <span v-if="instanceLabel"> · {{ instanceLabel }}</span>
        </div>
        <div v-if="languageLabel || categoryLabel" class="video-card-taxonomy">
          <span v-if="languageLabel" class="video-card-chip">{{ languageLabel }}</span>
          <span v-if="categoryLabel" class="video-card-chip">{{ categoryLabel }}</span>
        </div>
        <div class="video-card-stats" aria-label="Video reactions">
          <span class="stat likes"><span v-html="iconThumbUp()"></span><span data-stat="likes">{{ formatStatValue(likes) }}</span></span>
          <span class="stat dislikes"><span v-html="iconThumbDown()"></span><span data-stat="dislikes">{{ formatStatValue(dislikes) }}</span></span>
        </div>
      </div>
      <button class="video-card-menu" type="button" aria-label="More options" title="More options">
        <span aria-hidden="true">⋮</span>
      </button>
    </div>
  </article>
</template>
