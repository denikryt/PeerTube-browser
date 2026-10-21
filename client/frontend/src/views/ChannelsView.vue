<script setup lang="ts">
/** Channel browser route preserving the Client `/api/channels` behavior. */
import { computed, onMounted } from "vue";
import StatusBlock from "../components/StatusBlock.vue";
import { useChannels, type ChannelSortKey } from "../composables/useChannels";
import { channelLabel, channelUrl } from "../components/channel-row";
import { formatStatValue } from "../utils/format";

const { state, load, toggleSort } = useChannels();
const pageCount = computed(() => Math.max(1, Math.ceil(state.total / state.pageSize)));
const from = computed(() => state.total > 0 ? (state.page - 1) * state.pageSize + 1 : 0);
const to = computed(() => state.total > 0 ? Math.min(state.total, from.value + state.rows.length - 1) : 0);
const checkedFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });

onMounted(() => void load());

function clearFilters() {
  state.q = "";
  state.instance = "";
  state.minFollowers = 0;
  state.minVideos = 0;
  state.maxVideos = null;
  state.page = 1;
  void load();
}

function sortBy(key: ChannelSortKey) {
  toggleSort(key);
  void load();
}

function nextPage() {
  if (state.page >= pageCount.value) return;
  state.page += 1;
  void load();
}

function prevPage() {
  if (state.page <= 1) return;
  state.page -= 1;
  void load();
}
</script>

<template>
  <main class="channels-main">
    <form class="controls" @submit.prevent="state.page = 1; load()">
      <label class="control">Search<input v-model="state.q" type="search" placeholder="linux" /></label>
      <label class="control">Instance<input v-model="state.instance" type="text" placeholder="example.org" /></label>
      <label class="control">Min followers<input v-model.number="state.minFollowers" type="number" min="0" /></label>
      <label class="control">Min videos<input v-model.number="state.minVideos" type="number" min="0" /></label>
      <label class="control">Max videos<input v-model.number="state.maxVideos" type="number" min="0" /></label>
      <button class="ghost-button" type="submit">Apply</button>
      <button class="ghost-button" type="button" @click="clearFilters">Clear</button>
    </form>

    <section class="summary">
      <div>
        <div v-if="state.loading">Loading...</div>
        <div v-else-if="state.total === 0">No channels found</div>
        <div v-else>Showing {{ formatStatValue(from) }}-{{ formatStatValue(to) }} of {{ formatStatValue(state.total) }} channels</div>
        <div class="summary-meta">{{ state.generatedAt ? `Updated ${checkedFormat.format(new Date(state.generatedAt))}` : "" }}</div>
      </div>
      <div class="pager">
        <button class="ghost-button" type="button" :disabled="state.page <= 1 || state.loading" @click="prevPage">Prev</button>
        <span class="page-status">{{ state.page }} / {{ pageCount }}</span>
        <button class="ghost-button" type="button" :disabled="state.page >= pageCount || state.loading" @click="nextPage">Next</button>
        <label class="page-size">Page size
          <select v-model.number="state.pageSize" @change="state.page = 1; load()">
            <option :value="25">25</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </label>
      </div>
    </section>

    <StatusBlock v-if="state.error" kind="error" :message="state.error" />
    <div class="table-wrap">
      <table class="channels-table">
        <thead>
          <tr>
            <th></th>
            <th><button type="button" @click="sortBy('name')">Channel</button></th>
            <th><button type="button" @click="sortBy('instance')">Instance</button></th>
            <th><button type="button" @click="sortBy('videos')">Videos</button></th>
            <th><button type="button" @click="sortBy('followers')">Followers</button></th>
            <th><button type="button" @click="sortBy('checked')">Checked</button></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="state.loading"><td class="empty" colspan="6">Loading...</td></tr>
          <tr v-else-if="state.rows.length === 0"><td class="empty" colspan="6">No results found.</td></tr>
          <tr v-for="row in state.rows" v-else :key="`${row.instance_domain}::${row.channel_id}`">
            <td class="avatar-cell"><img v-if="row.avatar_url" class="avatar" :src="row.avatar_url" alt="" loading="lazy" /><div v-else class="avatar-fallback">—</div></td>
            <td><div class="channel-cell"><a class="channel-name" :href="channelUrl(row)" target="_blank" rel="noreferrer">{{ channelLabel(row) }}</a><div class="channel-meta">{{ row.instance_domain }}</div></div></td>
            <td>{{ row.instance_domain }}</td>
            <td class="num">{{ formatStatValue(row.videos_count) }}</td>
            <td class="num">{{ formatStatValue(row.followers_count) }}</td>
            <td class="num">{{ row.health_checked_at ? checkedFormat.format(new Date(row.health_checked_at)) : "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
