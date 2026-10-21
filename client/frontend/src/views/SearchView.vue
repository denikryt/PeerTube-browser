<script setup lang="ts">
/** Dedicated Search page backed by public Client Search API v1 routes. */
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import ChannelResultRow from "../components/ChannelResultRow.vue";
import StatusBlock from "../components/StatusBlock.vue";
import VideoCard from "../components/VideoCard.vue";
import { useSearch } from "../composables/useSearch";

const route = useRoute();
const router = useRouter();
const input = ref(String(route.query.q ?? ""));
const { state, search } = useSearch();

onMounted(() => void search(input.value));
watch(() => route.query.q, (value) => {
  input.value = String(value ?? "");
  void search(input.value);
});

function submit() {
  const q = input.value.trim();
  router.replace({ path: "/search", query: q ? { q } : {} });
}

function clear() {
  input.value = "";
  router.replace({ path: "/search" });
}
</script>

<template>
  <main class="videos-main">
    <form class="search-bar" role="search" @submit.prevent="submit">
      <label class="search-label" for="search-input">Search videos and channels</label>
      <div class="search-controls">
        <input id="search-input" v-model="input" type="search" autocomplete="off" placeholder="Search videos and channels" />
        <button class="search-button" type="submit">Search</button>
        <button v-if="input" class="ghost-button" type="button" @click="clear">Clear</button>
      </div>
    </form>

    <section v-if="!state.q" class="search-landing" aria-label="Search videos">
      <h2>Search videos</h2>
      <p>Use the search box above to find videos by title, channel, tag, category, or instance.</p>
    </section>

    <section v-else class="search-results">
      <div class="search-results-heading">Search results for “{{ state.q }}”</div>
      <section class="search-section">
        <h2>Videos</h2>
        <StatusBlock v-if="state.loadingVideos" message="Searching videos..." />
        <StatusBlock v-else-if="state.videoError" kind="error" :message="state.videoError" />
        <StatusBlock v-else-if="state.videos.length === 0" kind="empty" message="No videos found" />
        <div v-else class="cards-grid">
          <VideoCard v-for="row in state.videos" :key="`${row.instance_domain ?? row.instanceDomain}::${row.video_uuid ?? row.videoUuid ?? row.video_id}`" :row="row" />
        </div>
      </section>
      <section class="search-section">
        <h2>Channels</h2>
        <StatusBlock v-if="state.loadingChannels" message="Searching channels..." />
        <StatusBlock v-else-if="state.channelError" kind="error" :message="state.channelError" />
        <StatusBlock v-else-if="state.channels.length === 0" kind="empty" message="No channels found" />
        <div v-else class="channel-results-list">
          <ChannelResultRow v-for="row in state.channels" :key="`${row.instance_domain}::${row.channel_id}`" :row="row" />
        </div>
      </section>
    </section>
  </main>
</template>
