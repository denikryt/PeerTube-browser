<script setup lang="ts">
/** Shared global video-filter controls for Home and Search. */
import { onMounted, ref } from "vue";
import { fetchVideoFacetsPayload } from "../data/video-facets";
import type { VideoFacetsPayload, VideoFilters } from "../types/video-filters";

const props = defineProps<{ filters: VideoFilters }>();
const emit = defineEmits<{ change: [filters: VideoFilters] }>();

const facets = ref<VideoFacetsPayload | null>(null);
const facetsLoading = ref(false);
const facetsError = ref("");

/** Load facet options independently from the page's feed/search request. */
async function loadFacets(): Promise<void> {
  facetsLoading.value = true;
  facetsError.value = "";
  try {
    facets.value = await fetchVideoFacetsPayload();
  } catch (error) {
    facetsError.value = error instanceof Error ? error.message : "Failed to load filters";
  } finally {
    facetsLoading.value = false;
  }
}

/** Read one form-control value without embedding casts in the template. */
function eventValue(event: Event): string {
  const target = event.target;
  return target instanceof HTMLInputElement || target instanceof HTMLSelectElement ? target.value : "";
}

/** Emit one complete immutable filter selection to the page that owns the URL. */
function setFilter(key: keyof VideoFilters, value: string): void {
  emit("change", { ...props.filters, [key]: value.trim() || null });
}

/** Clear all four dimensions through the same complete-selection event. */
function clearFilters(): void {
  emit("change", { language: null, category: null, tag: null, instance: null });
}

onMounted(() => void loadFacets());
</script>

<template>
  <section class="video-filters" aria-label="Video filters">
    <label>
      <span>Language</span>
      <select :value="filters.language ?? ''" @change="setFilter('language', eventValue($event))">
        <option value="">All</option>
        <option
          v-if="filters.language && !facets?.languages.some((item) => item.value === filters.language)"
          :value="filters.language"
        >{{ filters.language }}</option>
        <option v-for="item in facets?.languages ?? []" :key="item.value" :value="item.value">
          {{ item.label || item.value }} ({{ item.count }})
        </option>
      </select>
    </label>
    <label>
      <span>Category</span>
      <select :value="filters.category ?? ''" @change="setFilter('category', eventValue($event))">
        <option value="">All</option>
        <option
          v-if="filters.category && !facets?.categories.some((item) => item.value === filters.category)"
          :value="filters.category"
        >{{ filters.category }}</option>
        <option v-for="item in facets?.categories ?? []" :key="item.value" :value="item.value">
          {{ item.value }} ({{ item.count }})
        </option>
      </select>
    </label>
    <label>
      <span>Tag</span>
      <input :value="filters.tag ?? ''" list="video-filter-tag-options" @change="setFilter('tag', eventValue($event))" />
      <datalist id="video-filter-tag-options">
        <option v-for="item in facets?.tags ?? []" :key="item.value" :value="item.value">{{ item.count }}</option>
      </datalist>
    </label>
    <label>
      <span>Instance</span>
      <input :value="filters.instance ?? ''" list="video-filter-instance-options" @change="setFilter('instance', eventValue($event))" />
      <datalist id="video-filter-instance-options">
        <option v-for="item in facets?.instances ?? []" :key="item.value" :value="item.value">{{ item.count }}</option>
      </datalist>
    </label>
    <button class="ghost-button" type="button" @click="clearFilters">Clear filters</button>
  </section>

  <div v-if="facetsLoading" class="filter-status">Loading filter options…</div>
  <div v-else-if="facetsError" class="filter-status error-inline">
    Filter options unavailable: {{ facetsError }}
    <button class="ghost-button" type="button" @click="loadFacets">Retry</button>
  </div>
</template>
