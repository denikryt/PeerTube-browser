<script setup lang="ts">
/**
 * Render one thumbnail source at a time and advance only after an image error.
 *
 * Browser fallback ownership lives here so feed and similar-video cards share
 * the same sequential loading lifecycle without prefetching remote candidates.
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { ThumbnailCandidate } from "../types/videos";
import { reserveThumbnailRequestStart } from "../utils/thumbnail-request-scheduler";

const DEFAULT_THUMBNAIL_URL = "/default-video-thumbnail.svg";
const props = defineProps<{
  /** Full Client API candidates let the browser select an efficient card source. */
  candidates?: readonly ThumbnailCandidate[];
  /** URL-only compatibility input for callers not yet sending candidate metadata. */
  urls?: readonly string[];
  alt: string;
}>();

const MINIMUM_WIDTH = 500;
const MINIMUM_HEIGHT = 300;

/** Return valid URL-only compatibility candidates when full metadata is absent. */
function legacyCandidates(urls: readonly string[] | undefined): ThumbnailCandidate[] {
  if (!urls) return [];
  const seen = new Set<string>();
  const candidates: ThumbnailCandidate[] = [];
  for (const value of urls) {
    const url = value.trim();
    if (!url || seen.has(url)) continue;
    seen.add(url);
    candidates.push({ url, width: null, height: null });
  }
  return candidates;
}

/** Select the smallest usable card image and retain every other source for error fallback. */
function orderedSources(candidates: readonly ThumbnailCandidate[]): string[] {
  if (!candidates.length) return [];
  const eligible = candidates.filter(
    (candidate) => candidate.width !== null
      && candidate.height !== null
      && candidate.width >= MINIMUM_WIDTH
      && candidate.height >= MINIMUM_HEIGHT
  );
  // PeerTube ordering is largest first. Pick the least-area acceptable source so
  // feed cards avoid downloading 1080p artwork when a 850x480 image is available.
  const selected = eligible.reduce<ThumbnailCandidate | null>((best, candidate) => {
    if (best === null) return candidate;
    return candidate.width! * candidate.height! < best.width! * best.height!
      ? candidate
      : best;
  }, null) ?? candidates[0];
  return [selected.url, ...candidates.filter((candidate) => candidate.url !== selected.url).map((candidate) => candidate.url)];
}

// A present empty candidate array is authoritative. URL-only props are only a
// compatibility path for old component callers that do not provide candidates.
const sources = computed(() => orderedSources(props.candidates ? [...props.candidates] : legacyCandidates(props.urls)));

// The terminal local default is represented by index === urls.length, so one
// state variable owns the entire remote-candidate -> local-default sequence.
const index = ref(0);
const currentSrc = ref(DEFAULT_THUMBNAIL_URL);
const isThumbnailLoading = ref(false);
let sourceTimer: ReturnType<typeof globalThis.setTimeout> | null = null;
let sourceGeneration = 0;

/** Apply one source now or after its shared-host request slot becomes available. */
function requestCurrentSource() {
  sourceGeneration += 1;
  const generation = sourceGeneration;
  if (sourceTimer !== null) {
    globalThis.clearTimeout(sourceTimer);
    sourceTimer = null;
  }
  const source = sources.value[index.value];
  if (!source) {
    isThumbnailLoading.value = false;
    currentSrc.value = DEFAULT_THUMBNAIL_URL;
    return;
  }
  isThumbnailLoading.value = true;
  const delay = reserveThumbnailRequestStart(source);
  if (delay === 0) {
    currentSrc.value = source;
    return;
  }
  // Show the local placeholder while waiting rather than keeping a known-broken
  // URL visible. Changing src after the slot starts the actual image request.
  currentSrc.value = DEFAULT_THUMBNAIL_URL;
  sourceTimer = globalThis.setTimeout(() => {
    if (generation === sourceGeneration) currentSrc.value = source;
  }, delay);
}

/** Reveal the remote image only after the browser has fully loaded it. */
function onLoad() {
  if (currentSrc.value !== DEFAULT_THUMBNAIL_URL) isThumbnailLoading.value = false;
}

/** Advance only after the currently rendered remote source fails. */
function onError() {
  // A missing local default is terminal; never turn its error into a retry loop.
  if (currentSrc.value === DEFAULT_THUMBNAIL_URL) {
    isThumbnailLoading.value = false;
    return;
  }
  if (index.value < sources.value.length) {
    index.value += 1;
    requestCurrentSource();
  }
}

// Callers replace the candidate array when the row changes; no deep traversal is needed.
watch(() => [props.candidates, props.urls], () => {
  index.value = 0;
  requestCurrentSource();
}, { immediate: true });

/** Do not let an unmounted card start a delayed remote request. */
onBeforeUnmount(() => {
  sourceGeneration += 1;
  if (sourceTimer !== null) globalThis.clearTimeout(sourceTimer);
});
</script>

<template>
  <span v-if="isThumbnailLoading" class="thumbnail-skeleton" aria-hidden="true"></span>
  <img
    :src="currentSrc"
    :alt="alt"
    :class="{ 'thumbnail-image--loading': isThumbnailLoading }"
    loading="lazy"
    @load="onLoad"
    @error="onError"
  />
</template>
