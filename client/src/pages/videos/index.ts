import "../../videos.css";
import { fetchSimilarVideosPayload, parseSimilarQuery, resolveApiBase } from "../../data/videos";
import { clearLocalLikes } from "../../data/local-likes";
import { fetchUserProfileLikes, resetUserProfileLikes } from "../../data/user-profile";
import type { SimilarSeed, VideoRow, VideosPayload } from "../../types/videos";

const cards = document.getElementById("video-cards");
const summaryCounts = document.getElementById("summary-counts");
const summaryMeta = document.getElementById("summary-meta");
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
const apiParam = params.get("api") ?? params.get("apiBase");

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
  } catch (error) {
    state.loading = false;
    const message = error instanceof Error ? error.message : "Load error";
    summaryCounts.textContent = "";
    summaryMeta.textContent = "";
    cards.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
  }
}

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

function renderCards(reset = false) {
  const visibleRows = visibleSample();
  if (!visibleRows.length) {
    cards.innerHTML = `<div class="error">No videos found.</div>`;
    return;
  }

  if (reset) {
    cards.innerHTML = visibleRows.map((row) => renderCard(row)).join("");
    queueStatsForRows(visibleRows);
    return;
  }

  const existingCount = cards.querySelectorAll(".video-card").length;
  if (existingCount >= visibleRows.length) return;
  const newRows = visibleRows.slice(existingCount);
  const markup = newRows.map((row) => renderCard(row)).join("");
  cards.insertAdjacentHTML("beforeend", markup);
  queueStatsForRows(newRows);
}

function visibleSample() {
  return state.sample.slice(0, state.visibleCount);
}

function setupInfiniteScroll() {
  if (!feedSentinel) return;
  const observer = new IntersectionObserver(
    (entries) => {
      if (state.loading) return;
      if (!entries.some((entry) => entry.isIntersecting)) return;
      const nextCount = Math.min(state.sample.length, state.visibleCount + CHUNK_SIZE);
      if (nextCount > state.visibleCount) {
        state.visibleCount = nextCount;
        renderCards();
        renderSummary();
        return;
      }
    },
    { rootMargin: "200px" }
  );
  observer.observe(feedSentinel);
}

function renderCard(row: VideoRow) {
  const title = row.title ?? "Untitled video";
  const thumb = thumbnailUrl(row);
  const duration = formatDuration(row.duration ?? null);
  const stats = resolveCachedStats(row);
  const views = stats?.views ?? null;
  const likes = stats?.likes ?? null;
  const dislikes = stats?.dislikes ?? null;
  const channelLabel = channelName(row);
  const channelHref = channelUrl(row);
  const avatarUrl = channelAvatarUrl(row);
  const channelBadge = channelInitials(row);
  const publishedAt = publishedAtMs(row);
  const timeAgo = publishedAt ? formatTimeAgo(publishedAt) : null;
  const timeSuffix = timeAgo ? ` · ${timeAgo}` : "";
  const avatarMarkup = avatarUrl
    ? `<img src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" />`
    : `<span>${escapeHtml(channelBadge)}</span>`;
  const thumbMarkup = thumb
    ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
    : `<div class="thumb-fallback">No preview</div>`;
  const videoKey = resolveVideoKey(row);
  const keyAttribute = videoKey ? ` data-video-key="${escapeHtml(videoKey)}"` : "";
  const debugMarkup = renderDebugMetrics(row);

  return `
    <article class="video-card"${keyAttribute}>
      <a class="video-link" href="${escapeHtml(videoPageUrl(row))}">
        <div class="video-thumb">
          ${thumbMarkup}
          <span class="duration">${duration}</span>
        </div>
        <div class="video-body">
          <h3 class="video-title">${escapeHtml(title)}</h3>
          <div class="video-footer">
            <div class="channel-meta">
              <div class="channel-avatar" aria-hidden="true">${avatarMarkup}</div>
              <div class="channel-text">
                <a class="channel-link" href="${escapeHtml(channelHref)}" target="_blank" rel="noreferrer">
                  ${escapeHtml(channelLabel)}
                </a>
                <div class="video-meta"><span data-stat="views">${formatStatValue(views)}</span> views${escapeHtml(timeSuffix)}</div>
              </div>
            </div>
            <div class="video-stats">
              <span class="stat likes">${iconThumbUp()}<span data-stat="likes">${formatStatValue(likes)}</span></span>
              <span class="stat dislikes">${iconThumbDown()}<span data-stat="dislikes">${formatStatValue(dislikes)}</span></span>
            </div>
            ${debugMarkup}
          </div>
        </div>
      </a>
    </article>
  `;
}

function videoPageUrl(row: VideoRow) {
  const params = new URLSearchParams();
  const host = row.instance_domain ?? row.instanceDomain ?? "";
  const id = row.video_id ?? row.video_uuid ?? row.videoUuid ?? "";
  if (id) params.set("id", id);
  if (host) params.set("host", host);
  if (row.title) params.set("title", row.title);
  const channelLabel =
    row.channel_display_name ??
    row.channelDisplayName ??
    row.channel_name ??
    row.channelName ??
    "";
  if (channelLabel) params.set("channel", channelLabel);
  const channelHref = channelUrl(row);
  if (channelHref && channelHref !== "#") params.set("channelUrl", channelHref);
  const embed = embedUrl(row);
  if (embed) params.set("embed", embed);
  const original = videoUrl(row);
  if (original && original !== "#") params.set("url", original);
  if (apiParam) params.set("api", apiParam);
  return `/video-page.html?${params.toString()}`;
}

function videoUrl(row: VideoRow) {
  if (row.video_url) return row.video_url;
  if (row.videoUrl) return row.videoUrl;
  const uuid = row.video_uuid ?? row.videoUuid;
  const host = row.instance_domain ?? row.instanceDomain;
  if (uuid && host) {
    return `https://${host}/videos/watch/${encodeURIComponent(uuid)}`;
  }
  return "#";
}

function thumbnailUrl(row: VideoRow) {
  return row.thumbnail_url ?? row.thumbnailUrl ?? row.preview_path ?? row.previewPath ?? null;
}

function channelName(row: VideoRow) {
  return (
    row.channel_display_name ??
    row.channelDisplayName ??
    row.channel_name ??
    row.channelName ??
    "Unknown channel"
  );
}

function channelInitials(row: VideoRow) {
  const label = channelName(row).trim();
  if (!label) return "•";
  const cleaned = label.replace(/[_\-]+/g, " ").replace(/\s+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

function channelAvatarUrl(row: VideoRow) {
  return (
    row.channel_avatar_url ??
    row.channelAvatarUrl ??
    row.account_avatar_url ??
    row.accountAvatarUrl ??
    row.avatar_url ??
    row.avatarUrl ??
    null
  );
}

function channelUrl(row: VideoRow) {
  if (row.channel_url) return row.channel_url;
  if (row.channelUrl) return row.channelUrl;
  const name = row.channel_name ?? row.channelName;
  const host = row.instance_domain ?? row.instanceDomain;
  if (name && host) {
    return `https://${host}/video-channels/${encodeURIComponent(name)}`;
  }
  return "#";
}

function embedUrl(row: VideoRow) {
  const raw = row.embed_path ?? row.embedPath ?? "";
  if (raw.startsWith("http")) return raw;
  const host = row.instance_domain ?? row.instanceDomain;
  if (raw && host) {
    return `https://${host}${raw}`;
  }
  const uuid = row.video_uuid ?? row.videoUuid;
  if (uuid && host) {
    return `https://${host}/videos/embed/${encodeURIComponent(uuid)}`;
  }
  return "";
}

function publishedAtMs(row: VideoRow) {
  const raw = row.published_at ?? row.publishedAt ?? null;
  if (!raw || !Number.isFinite(raw)) return null;
  const value = Number(raw);
  if (value < 1e12) return value * 1000;
  return value;
}

function formatTimeAgo(timestampMs: number) {
  const now = Date.now();
  const diffMs = Math.max(0, now - timestampMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const month = 30 * day;
  const year = 365 * day;

  if (diffMs < minute) return "just now";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)} minutes ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)} hours ago`;
  if (diffMs < month) return `${Math.floor(diffMs / day)} days ago`;
  if (diffMs < year) return `${Math.floor(diffMs / month)} months ago`;
  return `${Math.floor(diffMs / year)} years ago`;
}

function formatDuration(value: number | null) {
  if (!value || !Number.isFinite(value)) return "0:00";
  const total = Math.max(0, Math.round(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function shuffle<T>(items: T[]) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

function iconThumbUp() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

function iconEye() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="3.2" />
    </svg>
  `;
}

function iconThumbDown() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

function renderDebugMetrics(row: VideoRow) {
  if (!debugMode) return "";
  const debug = row.debug ?? null;
  if (!debug) {
    return `<div class="video-debug empty">Debug not available</div>`;
  }
  const score = formatDebugNumber(debug.score);
  const similarity = formatDebugNumber(debug.similarity_score);
  const freshness = formatDebugNumber(debug.freshness_score);
  const popularity = formatDebugNumber(debug.popularity_score);
  const layer = debug.layer ?? "--";
  const rankBefore = formatDebugInt(debug.rank_before);
  const rankAfter = formatDebugInt(debug.rank_after);
  return `
    <div class="video-debug">
      <div><span class="label">score</span> ${score}</div>
      <div><span class="label">sim</span> ${similarity}</div>
      <div><span class="label">fresh</span> ${freshness}</div>
      <div><span class="label">pop</span> ${popularity}</div>
      <div><span class="label">layer</span> ${escapeHtml(layer)}</div>
      <div><span class="label">rank</span> ${rankBefore} → ${rankAfter}</div>
    </div>
  `;
}

function formatDebugNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return Number(value).toFixed(3);
}

function formatDebugInt(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return String(Math.trunc(value));
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "\"":
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return char;
    }
  });
}

function resolveCachedStats(row: VideoRow) {
  const key = resolveVideoKey(row);
  if (!key) return null;
  if (statsCache.has(key)) return statsCache.get(key) ?? null;
  if (hasServerStats(row)) return resolveServerStats(row);
  return null;
}

function resolveVideoKey(row: VideoRow) {
  const host = resolveInstanceDomain(row);
  const id = resolveVideoId(row);
  if (!host || !id) return null;
  return `${host}::${id}`;
}

function resolveInstanceDomain(row: VideoRow) {
  return row.instance_domain ?? row.instanceDomain ?? "";
}

function resolveVideoId(row: VideoRow) {
  const value = row.video_uuid ?? row.videoUuid ?? row.video_id ?? "";
  return value ? String(value) : "";
}

function formatStatValue(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return numberFormat.format(value);
}

function normalizeStatValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function hasServerStats(row: VideoRow) {
  const hasViews =
    Object.prototype.hasOwnProperty.call(row, "views") ||
    Object.prototype.hasOwnProperty.call(row, "viewsCount") ||
    Object.prototype.hasOwnProperty.call(row, "views_count");
  const hasLikes =
    Object.prototype.hasOwnProperty.call(row, "likes") ||
    Object.prototype.hasOwnProperty.call(row, "likesCount") ||
    Object.prototype.hasOwnProperty.call(row, "likes_count");
  return hasViews && hasLikes;
}

function resolveServerStats(row: VideoRow) {
  return {
    views: normalizeStatValue(row.views ?? row.viewsCount ?? row.views_count),
    likes: normalizeStatValue(row.likes ?? row.likesCount ?? row.likes_count),
    dislikes: normalizeStatValue(row.dislikes ?? row.dislikesCount ?? row.dislikes_count)
  };
}

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

function openProfileModal(likes: VideoRow[]) {
  if (!profileModal || !profileModalBody) return;
  profileModalBody.innerHTML = renderLikes(likes);
  profileModal.removeAttribute("hidden");
  profileModalBody.focus();
}

function closeProfileModal() {
  if (!profileModal) return;
  profileModal.setAttribute("hidden", "true");
}

function renderLikes(likes: VideoRow[]) {
  if (!likes.length) {
    return `<div class="empty">No likes yet.</div>`;
  }
  return likes
    .map((row) => {
      const title = row.title ?? "Untitled";
      const thumb = thumbnailUrl(row);
      const link = videoPageUrl(row);
      const channel = channelName(row);
      const host = row.instance_domain ?? row.instanceDomain ?? "";
      const meta = host ? `${channel} · ${host}` : channel;
      const thumbMarkup = thumb
        ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
        : `<div class="thumb-fallback">No preview</div>`;
      return `
        <a class="like-card" href="${escapeHtml(link)}">
          <div class="like-thumb">${thumbMarkup}</div>
          <h3 class="like-title">${escapeHtml(title)}</h3>
          <div class="like-meta">${escapeHtml(meta)}</div>
        </a>
      `;
    })
    .join("");
}

function resolveFeedMode(searchParams: URLSearchParams) {
  const raw = searchParams.get("mode");
  return raw === "random" ? "random" : "recommendations";
}

function setFeedMode(mode: "random" | "recommendations") {
  const next = new URLSearchParams(window.location.search);
  if (mode === "random") {
    next.set("mode", "random");
  } else {
    next.delete("mode");
  }
  next.delete("similarId");
  next.delete("id");
  next.delete("video_id");
  next.delete("videoId");
  next.delete("uuid");
  next.delete("video_uuid");
  window.location.search = next.toString();
}
