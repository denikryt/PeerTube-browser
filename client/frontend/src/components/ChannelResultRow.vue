<script setup lang="ts">
/** Compact channel row used by Search results. */
import type { ChannelRow } from "../types/channels";
import { channelLabel, channelUrl } from "./channel-row";
import { formatStatValue } from "../utils/format";

defineProps<{ row: ChannelRow }>();
</script>

<template>
  <a class="channel-result" :href="channelUrl(row)" target="_blank" rel="noreferrer">
    <img v-if="row.avatar_url" class="channel-result-avatar" :src="row.avatar_url" alt="" loading="lazy" />
    <span v-else class="channel-result-avatar channel-result-avatar-fallback">—</span>
    <span class="channel-result-body">
      <strong>{{ channelLabel(row) }}</strong>
      <span>{{ row.instance_domain }} · {{ formatStatValue(row.videos_count) }} videos · {{ formatStatValue(row.followers_count) }} followers</span>
    </span>
  </a>
</template>
