/**
 * Module `client/frontend/src/pages/videos/index.ts`: provide runtime functionality.
 */

import "../../videos.css";
import { fetchSimilarVideosPayload, parseSimilarQuery, resolveApiBase } from "../../api/client";
import { clearLocalLikes, fetchUserProfileLikes, resetUserProfileLikes } from "../../api/client";
import { renderFeedVideoCard, resolveServerStats } from "../../components/video-card";
import { renderProfileLikes } from "../../components/profile-modal";
import { renderError } from "../../components/status";
import { formatStatValue, normalizeStatValue } from "../../utils/format";
import { hasServerStats, resolveInstanceDomain, resolveVideoId, resolveVideoKey } from "../../utils/video-fields";
import { resolveFeedMode, setFeedMode } from "../../state/feed-mode";
import type { SimilarSeed, VideoRow, VideosPayload } from "../../types/videos";

const cards = document.getElementById("video-cards")!;
const summaryCounts = document.getElementById("summary-counts")!;
const summaryMeta = document.getElementById("summary-meta")!;
const resetLink = document.getElementById("reset-feed") as HTMLAnchorElement | null;
const resetProfileButton = document.getElementById("reset-profile") as HTMLButtonElement | null;
const showProfileButton = document.getElementById("show-profile") as HTMLButtonElement | null;
const showRecommendationsButton = document.getElementById("show-recommendations") as HTMLButtonElement | null;
const showRandomButton = document.getElementById("show-random") as HTMLButtonElement | null;
const feedSentinel = document.getElementById("feed-sentinel");
const profileModal = document.getElementById("profile-modal");
const profileModalBody = document.getElementById("profile-modal-body") as HTMLDivElement | null;
const profileModalClose = document.getElementById("profile-modal-close") as HTMLButtonElement | null;

if (!cards || !summaryCounts || !summaryMeta) {
  throw new Error("Missing videos elements");
}

const numberFormat = new Intl.NumberFormat("en-US");
const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });
const CHUNK_SIZE = 6;
const params = new URLSearchParams(window.location.search);
const debugMode =
  params.get("debug") === "1" || document.body?.dataset.debug === "true";
if (debugMode && !params.get("debug")) {
  params.set("debug", "1");
}
const similarQuery = parseSimilarQuery(params);
const feedMode = resolveFeedMode(params);
const useSimilar = Boolean(similarQuery.id);
const apiBase = resolveApiBase(similarQuery);
const apiParam = params.get("api");

document.title = "PeerTube - Browser";

const state = {
  rows: [] as VideoRow[],
  sample: [] as VideoRow[],
  generatedAt: null as number | null,
  mode: "random" as "random" | "similar" | "personalized",
  seed: null as SimilarSeed | null,
  visibleCount: CHUNK_SIZE,
  loading: false
};
let feedObserver: IntersectionObserver | null = null;
let fallbackListenersAttached = false;

type LiveStats = {
  views: number | null;
  likes: number | null;
  dislikes: number | null;
};

const statsCache = new Map<string, LiveStats>();
const statsLoading = new Set<string>();

void loadVideos();

if (resetProfileButton) {
  resetProfileButton.addEventListener("click", async () => {
    resetProfileButton.disabled = true;
    try {
      clearLocalLikes();
      await resetUserProfileLikes(apiBase);
      await loadVideos();
    } finally {
      resetProfileButton.disabled = false;
    }
  });
}

if (showProfileButton) {
  showProfileButton.addEventListener("click", async () => {
    showProfileButton.disabled = true;
    try {
      const likes = await fetchUserProfileLikes(apiBase);
      openProfileModal(likes);
    } finally {
      showProfileButton.disabled = false;
    }
  });
}

if (showRecommendationsButton) {
  showRecommendationsButton.addEventListener("click", () => {
    setFeedMode("recommendations");
  });
}

if (showRandomButton) {
  showRandomButton.addEventListener("click", () => {
    setFeedMode("random");
  });
}

if (profileModalClose) {
  profileModalClose.addEventListener("click", () => closeProfileModal());
}

if (profileModal) {
  profileModal.addEventListener("click", (event) => {
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (target.hasAttribute("data-modal-close")) {
      closeProfileModal();
    }
  });
}

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (profileModal?.hasAttribute("hidden")) return;
  closeProfileModal();
});

/**
 * Handle load videos.
 */
async function loadVideos() {
  state.loading = true;
  summaryCounts.textContent = "";
  summaryMeta.textContent = "";
  if (resetLink) resetLink.hidden = true;
  cards.innerHTML = `<div class="loading">Loading...</div>`;
  setupInfiniteScroll();

  try {
    const payload = await fetchVideosPayload();
    state.loading = false;
    const rows = Array.isArray(payload) ? payload : payload.rows ?? [];
    state.rows = rows;
    state.generatedAt = Array.isArray(payload) ? null : payload.generatedAt ?? null;
    state.mode = useSimilar ? "similar" : feedMode === "random" ? "random" : "personalized";
    state.seed = Array.isArray(payload)
      ? null
      : ((payload as VideosPayload & { seed?: SimilarSeed }).seed ?? null);
    pickSample();
    renderCards(true);
    renderSummary();
    maybeFillViewport();
  } catch (error) {
    state.loading = false;
    const message = error instanceof Error ? error.message : "Load error";
    summaryCounts.textContent = "";
    summaryMeta.textContent = "";
    cards.innerHTML = renderError(message);
  }
}

/**
 * Handle fetch videos payload.
 */
async function fetchVideosPayload() {
  if (useSimilar) {
    return fetchSimilarVideosPayload(similarQuery);
  }
  if (feedMode === "random") {
    return fetchSimilarVideosPayload({
      ...similarQuery,
      apiBase,
      random: "1"
    });
  }
  const query = {
    ...similarQuery,
    apiBase
  };
  return fetchSimilarVideosPayload(query);
}

/**
 * Handle pick sample.
 */
function pickSample() {
  if (state.mode === "similar") {
    state.sample = state.rows.slice();
    state.visibleCount = CHUNK_SIZE;
    return;
  }
  if (state.mode === "personalized") {
    state.sample = state.rows.slice();
    state.visibleCount = CHUNK_SIZE;
    return;
  }
  const shuffled = shuffle([...state.rows]);
  state.sample = shuffled;
  state.visibleCount = CHUNK_SIZE;
}

/**
 * Handle render summary.
 */
function renderSummary() {
  const total = state.rows.length;
  const visible = Math.min(state.visibleCount, state.sample.length);
  if (state.mode === "similar") {
    summaryCounts.textContent = "";
    summaryMeta.textContent = "";
    if (resetLink) resetLink.hidden = false;
    return;
  }
  if (state.mode === "personalized") {
    summaryCounts.textContent = "";
    summaryMeta.textContent = "";
    if (resetLink) resetLink.hidden = true;
    return;
  }
  summaryCounts.textContent = "";
  summaryMeta.textContent = "";
  if (resetLink) resetLink.hidden = true;
}

/**
 * Handle render cards.
 */
function renderCards(reset = false) {
  const visibleRows = visibleSample();
  if (!visibleRows.length) {
    cards.innerHTML = `<div class="error">No videos found.</div>`;
    return;
  }

  if (reset) {
    cards.innerHTML = visibleRows.map((row) => renderFeedVideoCard(row, { apiParam, debugMode, stats: resolveCachedStats(row), videoKey: resolveVideoKey(row) })).join("");
    queueStatsForRows(visibleRows);
    return;
  }

  const existingCount = cards.querySelectorAll(".video-card").length;
  if (existingCount >= visibleRows.length) return;
  const newRows = visibleRows.slice(existingCount);
  const markup = newRows.map((row) => renderFeedVideoCard(row, { apiParam, debugMode, stats: resolveCachedStats(row), videoKey: resolveVideoKey(row) })).join("");
  cards.insertAdjacentHTML("beforeend", markup);
  queueStatsForRows(newRows);
}

/**
 * Handle visible sample.
 */
function visibleSample() {
  return state.sample.slice(0, state.visibleCount);
}

/**
 * Handle load next chunk.
 */
function loadNextChunk() {
  const nextCount = Math.min(state.sample.length, state.visibleCount + CHUNK_SIZE);
  if (nextCount <= state.visibleCount) return false;
  state.visibleCount = nextCount;
  renderCards();
  renderSummary();
  return true;
}

/**
 * Handle maybe fill viewport.
 */
function maybeFillViewport() {
  if (state.loading) return;
  let safety = 0;
  // If there is no scroll yet, keep appending chunks until the page can scroll.
  while (
    state.visibleCount < state.sample.length &&
    document.documentElement.scrollHeight <= window.innerHeight + 120 &&
    safety < 50
  ) {
    const changed = loadNextChunk();
    if (!changed) break;
    safety += 1;
  }
}

/**
 * Handle maybe load on scroll.
 */
function maybeLoadOnScroll() {
  if (state.loading) return;
  const nearBottom =
    window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;
  if (nearBottom) {
    loadNextChunk();
  }
}

/**
 * Handle setup infinite scroll.
 */
function setupInfiniteScroll() {
  if (feedObserver) {
    feedObserver.disconnect();
    feedObserver = null;
  }
  if (feedSentinel) {
    feedObserver = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        loadNextChunk();
      },
      { rootMargin: "200px" }
    );
    feedObserver.observe(feedSentinel);
  }
  if (!fallbackListenersAttached) {
    window.addEventListener("scroll", maybeLoadOnScroll, { passive: true });
    window.addEventListener("resize", () => {
      maybeLoadOnScroll();
      maybeFillViewport();
    });
    fallbackListenersAttached = true;
  }
}

/**
 * Handle resolve cached stats.
 */
function resolveCachedStats(row: VideoRow) {
  const key = resolveVideoKey(row);
  if (!key) return null;
  if (statsCache.has(key)) return statsCache.get(key) ?? null;
  if (hasServerStats(row)) return resolveServerStats(row);
  return null;
}

/**
 * Handle queue stats for rows.
 */
function queueStatsForRows(rows: VideoRow[]) {
  if (!rows.length) return;
  const groups = new Map<string, { key: string; id: string }[]>();

  for (const row of rows) {
    const host = resolveInstanceDomain(row);
    const id = resolveVideoId(row);
    if (!host || !id) continue;
    const key = `${host}::${id}`;
    if (hasServerStats(row)) {
      if (!statsCache.has(key)) {
        statsCache.set(key, resolveServerStats(row));
      }
      continue;
    }
    const cached = statsCache.get(key);
    if (cached) {
      applyStatsToDom(key, cached);
      continue;
    }
    if (statsLoading.has(key)) continue;
    statsLoading.add(key);
    const batch = groups.get(host) ?? [];
    batch.push({ key, id });
    groups.set(host, batch);
  }

  for (const [host, entries] of groups) {
    void fetchStatsForHost(host, entries);
  }
}

/**
 * Handle fetch stats for host.
 */
async function fetchStatsForHost(host: string, entries: { key: string; id: string }[]) {
  const ids = entries.map((entry) => entry.id);
  try {
    const statsById = await fetchBatchStats(host, ids);
    const missing: { key: string; id: string }[] = [];
    for (const entry of entries) {
      if (!statsById.has(entry.id)) {
        missing.push(entry);
        continue;
      }
      const stats = statsById.get(entry.id) ?? { views: null, likes: null, dislikes: null };
      statsCache.set(entry.key, stats);
      statsLoading.delete(entry.key);
      applyStatsToDom(entry.key, stats);
    }
    if (missing.length) {
      await fetchStatsIndividually(host, missing);
    }
  } catch {
    await fetchStatsIndividually(host, entries);
  }
}

/**
 * Handle fetch stats individually.
 */
async function fetchStatsIndividually(host: string, entries: { key: string; id: string }[]) {
  await Promise.all(
    entries.map(async (entry) => {
      try {
        const stats = await fetchSingleStats(host, entry.id);
        const normalized = stats ?? { views: null, likes: null, dislikes: null };
        statsCache.set(entry.key, normalized);
        applyStatsToDom(entry.key, normalized);
      } finally {
        statsLoading.delete(entry.key);
      }
    })
  );
}

/**
 * Handle fetch batch stats.
 */
async function fetchBatchStats(host: string, ids: string[]) {
  const url = new URL(`https://${host}/api/v1/videos`);
  for (const id of ids) {
    url.searchParams.append("id", id);
  }
  url.searchParams.set("count", String(ids.length));
  const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error("Batch stats request failed");
  }
  const payload = (await response.json()) as Record<string, unknown>;
  const data = Array.isArray(payload.data) ? payload.data : null;
  if (!data) {
    throw new Error("Unexpected batch stats response");
  }
  const stats = new Map<string, LiveStats>();
  for (const item of data) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const uuid = record.uuid ?? record.video_uuid ?? record.videoUuid;
    const id = record.id ?? record.video_id ?? record.videoId;
    const views = normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
    const likes = normalizeStatValue(record.likes ?? record.likesCount ?? record.likes_count);
    const dislikes = normalizeStatValue(record.dislikes ?? record.dislikesCount ?? record.dislikes_count);
    const entry = { views, likes, dislikes };
    if (uuid) stats.set(String(uuid), entry);
    if (id) stats.set(String(id), entry);
  }
  return stats;
}

/**
 * Handle fetch single stats.
 */
async function fetchSingleStats(host: string, id: string) {
  const url = `https://${host}/api/v1/videos/${encodeURIComponent(id)}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) return null;
  const record = (await response.json()) as Record<string, unknown>;
  const views = normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
  const likes = normalizeStatValue(record.likes ?? record.likesCount ?? record.likes_count);
  const dislikes = normalizeStatValue(record.dislikes ?? record.dislikesCount ?? record.dislikes_count);
  return { views, likes, dislikes };
}

/**
 * Handle apply stats to dom.
 */
function applyStatsToDom(key: string, stats: LiveStats) {
  const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(key) : key;
  const card = cards.querySelector<HTMLElement>(`[data-video-key="${escaped}"]`);
  if (!card) return;
  const viewsEl = card.querySelector<HTMLElement>('[data-stat="views"]');
  if (viewsEl) viewsEl.textContent = formatStatValue(stats.views);
  const likesEl = card.querySelector<HTMLElement>('[data-stat="likes"]');
  if (likesEl) likesEl.textContent = formatStatValue(stats.likes);
  const dislikesEl = card.querySelector<HTMLElement>('[data-stat="dislikes"]');
  if (dislikesEl) dislikesEl.textContent = formatStatValue(stats.dislikes);
}

/**
 * Handle open profile modal.
 */
function openProfileModal(likes: VideoRow[]) {
  if (!profileModal || !profileModalBody) return;
  profileModalBody.innerHTML = renderProfileLikes(likes, apiParam);
  profileModal.removeAttribute("hidden");
  profileModalBody.focus();
}

/**
 * Handle close profile modal.
 */
function closeProfileModal() {
  if (!profileModal) return;
  profileModal.setAttribute("hidden", "true");
}


/** Shuffle items with the current Fisher-Yates behavior used by random feed mode. */
function shuffle<T>(items: T[]) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}
