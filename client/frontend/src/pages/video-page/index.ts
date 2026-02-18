/**
 * Module `client/frontend/src/pages/video-page/index.ts`: provide runtime functionality.
 */

import "../../video.css";
import { fetchSimilarVideosPayload, resolveApiBase } from "../../data/videos";
import { sendUserAction } from "../../data/user-actions";
import { addLocalLike } from "../../data/local-likes";
import type { VideoRow } from "../../types/videos";

const titleEl = document.getElementById("video-title");
const channelEl = document.getElementById("video-channel");
const channelAvatarEl = document.getElementById("channel-avatar");
const channelSubscribersEl = document.getElementById("channel-subscribers");
const publishedEl = document.getElementById("video-published");
const instanceMetaEl = document.getElementById("instance-meta");
const instanceAvatarEl = document.getElementById("instance-avatar");
const instanceLinkEl = document.getElementById("instance-link") as HTMLAnchorElement | null;
const accountMetaEl = document.getElementById("account-meta");
const accountAvatarEl = document.getElementById("account-avatar");
const accountLinkEl = document.getElementById("account-link") as HTMLAnchorElement | null;
const viewsEl = document.getElementById("video-views");
const descriptionEl = document.getElementById("video-description");
const embedEl = document.getElementById("video-embed") as HTMLIFrameElement | null;
const originalLink = document.getElementById("original-link") as HTMLAnchorElement | null;
const similarLink = document.getElementById("similar-link") as HTMLAnchorElement | null;
const likeButton = document.getElementById("like-button");
const dislikeButton = document.getElementById("dislike-button");
const likeCount = document.getElementById("like-count");
const dislikeCount = document.getElementById("dislike-count");
const similarSection = document.getElementById("similar-section");
const similarCards = document.getElementById("similar-videos");
const similarLinkInline = document.getElementById("similar-link-inline") as HTMLAnchorElement | null;
const statsNumberFormat = new Intl.NumberFormat("en-US");
let currentMetadata: VideoMetadata | null = null;

const params = new URLSearchParams(window.location.search);
const seedId = params.get("id");
const seedHost = params.get("host");
const apiBase = resolveApiBase({ apiBase: params.get("api") });
const fallback = {
  title: params.get("title") ?? "Video page",
  channel: params.get("channel") ?? "",
  channelUrl: params.get("channelUrl") ?? "",
  embed: params.get("embed") ?? "",
  url: params.get("url") ?? ""
};
const similarStatsCache = new Map<string, number | null>();
const similarStatsLoading = new Set<string>();

if (similarLink && seedId) {
  const search = new URLSearchParams();
  search.set("id", seedId);
  if (seedHost) search.set("host", seedHost);
  similarLink.href = `/videos.html?${search.toString()}`;
}

void loadVideo();
void loadSimilarVideos();

if (likeButton && dislikeButton) {
  likeButton.addEventListener("click", () => {
    const isActive = toggleReaction(likeButton, dislikeButton);
    if (isActive) {
      void handleLikeAction();
    }
  });
  dislikeButton.addEventListener("click", () => toggleReaction(dislikeButton, likeButton));
}

/**
 * Handle load video.
 */
async function loadVideo() {
  const metadata = await fetchVideoMetadata();
  currentMetadata = metadata;
  const channelUrl = metadata?.channelUrl || fallback.channelUrl;
  const channel = [
    metadata?.channelName,
    fallback.channel,
    labelFromUrl(channelUrl)
  ]
    .map((value) => value?.trim())
    .find((value) => value);
  const title = metadata?.title ?? fallback.title;
  const avatarUrl = metadata?.channelAvatarUrl ?? "";
  const subscribersCount = metadata?.subscribersCount ?? null;
  const embed = metadata?.embedUrl ?? fallback.embed;
  const original = metadata?.originalUrl ?? fallback.url;
  const views = metadata?.views ?? null;
  const likes = metadata?.likes ?? null;
  const dislikes = metadata?.dislikes ?? null;
  const description = metadata?.description ?? "";
  const publishedAt = metadata?.publishedAt ?? null;
  const timeAgo = publishedAt ? formatTimeAgo(publishedAt) : null;
  const instanceName = metadata?.instanceName ?? seedHost ?? "";
  const instanceUrl = metadata?.instanceUrl ?? (seedHost ? `https://${seedHost}` : "");
  const instanceAvatarUrl = metadata?.instanceAvatarUrl ?? "";
  const accountName = metadata?.accountName ?? "";
  const accountUrl = metadata?.accountUrl ?? "";
  const accountAvatarUrl = metadata?.accountAvatarUrl ?? "";

  document.title = `${title || "Video"} - PeerTube - Browser`;

  if (titleEl) titleEl.textContent = title || "Video page";
  const channelRowEl = channelEl?.closest(".channel-row") as HTMLElement | null;
  if (channelEl) {
    if (channel) {
      channelEl.innerHTML = channelUrl
        ? `<a href="${escapeHtml(channelUrl)}" target="_blank" rel="noreferrer">${escapeHtml(channel)}</a>`
        : escapeHtml(channel);
    } else {
      channelEl.textContent = "";
    }
  }
  if (channelAvatarEl) {
    const avatarMarkup = renderChannelAvatar(avatarUrl, channel || "");
    channelAvatarEl.innerHTML = avatarMarkup;
    channelAvatarEl.hidden = !avatarMarkup;
  }
  if (channelSubscribersEl) {
    if (Number.isFinite(subscribersCount ?? NaN)) {
      channelSubscribersEl.textContent = `${numberFormat().format(subscribersCount ?? 0)} subscribers`;
    } else {
      channelSubscribersEl.textContent = "";
    }
  }
  if (instanceMetaEl) {
    instanceMetaEl.hidden = !instanceName;
  }
  if (instanceLinkEl) {
    instanceLinkEl.textContent = instanceName;
    if (instanceUrl) {
      instanceLinkEl.href = instanceUrl;
    } else {
      instanceLinkEl.removeAttribute("href");
    }
  }
  if (instanceAvatarEl) {
    const initials = escapeHtml(instanceInitials(instanceName));
    if (instanceAvatarUrl) {
      instanceAvatarEl.classList.remove("fallback");
      instanceAvatarEl.innerHTML = `
        <img src="${escapeHtml(instanceAvatarUrl)}" alt="" loading="lazy"
          onerror="this.parentElement?.classList.add('fallback'); this.remove();" />
        <span>${initials}</span>
      `;
    } else {
      instanceAvatarEl.classList.add("fallback");
      instanceAvatarEl.innerHTML = `<span>${initials}</span>`;
    }
  }
  if (accountMetaEl) {
    accountMetaEl.hidden = !accountName;
  }
  if (accountLinkEl) {
    accountLinkEl.textContent = accountName;
    if (accountUrl) {
      accountLinkEl.href = accountUrl;
    } else {
      accountLinkEl.removeAttribute("href");
    }
  }
  if (accountAvatarEl) {
    const initials = escapeHtml(instanceInitials(accountName));
    if (accountAvatarUrl) {
      accountAvatarEl.classList.remove("fallback");
      accountAvatarEl.innerHTML = `
        <img src="${escapeHtml(accountAvatarUrl)}" alt="" loading="lazy"
          onerror="this.parentElement?.classList.add('fallback'); this.remove();" />
        <span>${initials}</span>
      `;
    } else {
      accountAvatarEl.classList.add("fallback");
      accountAvatarEl.innerHTML = `<span>${initials}</span>`;
    }
  }
  if (publishedEl) {
    publishedEl.textContent = timeAgo ? `${timeAgo}` : "";
  }
  if (channelRowEl) {
    const hasMeta = Boolean(channel || subscribersCount || timeAgo);
    channelRowEl.hidden = !hasMeta;
  }
  if (viewsEl) {
    const value = Number.isFinite(views ?? NaN) ? numberFormat().format(views ?? 0) : "0";
    const icon = iconEye();
    viewsEl.innerHTML = `${icon}<span class="metric-value">${value}</span>`;
  }
  if (likeCount) {
    likeCount.textContent = numberFormat().format(likes ?? 0);
  }
  if (dislikeCount) {
    dislikeCount.textContent = numberFormat().format(dislikes ?? 0);
  }
  if (descriptionEl) {
    descriptionEl.textContent = description ? description : "No description available.";
  }
  if (embedEl && embed) {
    embedEl.src = embed;
  }
  if (originalLink) {
    if (original) {
      originalLink.href = original;
    } else {
      originalLink.removeAttribute("href");
    }
  }
}

/**
 * Handle load similar videos.
 */
async function loadSimilarVideos() {
  if (!similarSection || !similarCards) return;
  if (!seedId) {
    similarSection.setAttribute("hidden", "true");
    return;
  }
  if (similarLinkInline) {
    const search = new URLSearchParams();
    search.set("id", seedId);
    if (seedHost) search.set("host", seedHost);
    similarLinkInline.href = `/videos.html?${search.toString()}`;
  }
  try {
    const payload = await fetchSimilarVideosPayload({
      id: seedId,
      host: seedHost,
      limit: "8",
      apiBase
    });
    const rows = payload.rows ?? [];
    if (!rows.length) {
      similarCards.innerHTML = `<div class="error">No similar videos found.</div>`;
      return;
    }
    similarCards.innerHTML = rows.map((row) => renderSimilarCard(row)).join("");
    queueSimilarStats(rows);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to load similar videos";
    similarCards.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
  }
}

/**
 * Handle channel name.
 */
function channelName(row: VideoRow | null) {
  return (
    row?.channel_display_name ??
    row?.channelDisplayName ??
    row?.channel_name ??
    row?.channelName ??
    row?.account_name ??
    row?.accountName ??
    ""
  );
}

/**
 * Handle channel initials.
 */
function channelInitials(label: string) {
  const trimmed = label.trim();
  if (!trimmed) return "•";
  const cleaned = trimmed.replace(/[_\-]+/g, " ").replace(/\s+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

/**
 * Handle render channel avatar.
 */
function renderChannelAvatar(avatarUrl: string, label: string) {
  if (avatarUrl) {
    return `<img src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" />`;
  }
  if (!label) return "";
  return `<span>${escapeHtml(channelInitials(label))}</span>`;
}

/**
 * Handle channel url for.
 */
function channelUrlFor(row: VideoRow | null) {
  if (!row) return "";
  if (row.channel_url) return row.channel_url;
  if (row.channelUrl) return row.channelUrl;
  if (row.account_url) return row.account_url;
  if (row.accountUrl) return row.accountUrl;
  const name = row.channel_name ?? row.channelName;
  const host = row.instance_domain ?? row.instanceDomain;
  if (name && host) {
    return `https://${host}/video-channels/${encodeURIComponent(name)}`;
  }
  return "";
}

/**
 * Handle label from url.
 */
function labelFromUrl(value: string) {
  if (!value) return "";
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean);
    return decodeURIComponent(parts[parts.length - 1] ?? "");
  } catch {
    return "";
  }
}

type VideoMetadata = {
  videoUuid?: string;
  title?: string;
  channelName?: string;
  channelUrl?: string;
  channelAvatarUrl?: string;
  subscribersCount?: number | null;
  instanceName?: string;
  instanceUrl?: string;
  instanceAvatarUrl?: string;
  accountName?: string;
  accountUrl?: string;
  accountAvatarUrl?: string;
  embedUrl?: string;
  originalUrl?: string;
  views?: number | null;
  likes?: number | null;
  dislikes?: number | null;
  description?: string;
  publishedAt?: number | null;
};

/**
 * Handle fetch video metadata.
 */
async function fetchVideoMetadata(): Promise<VideoMetadata | null> {
  const source = resolveVideoSource();
  if (!source?.host || !source.id) return null;
  const serverMeta = await fetchVideoMetadataFromServer(source);
  if (serverMeta) return serverMeta;
  return fetchVideoMetadataFromInstance(source);
}

/**
 * Handle fetch video metadata from server.
 */
async function fetchVideoMetadataFromServer(source: { host: string; id: string; url: string }) {
  try {
    const url = new URL("/api/video", apiBase);
    url.searchParams.set("id", source.id);
    url.searchParams.set("host", source.host);
    const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    const instanceMeta = await fetchInstanceMetadata(source.host);
    const publishedAt = normalizeTimestampMs(data.publishedAt);
    return {
      videoUuid: (data.videoUuid as string | undefined) ?? "",
      title: (data.title as string | undefined) ?? fallback.title,
      channelName: (data.channelName as string | undefined) ?? fallback.channel,
      channelUrl: (data.channelUrl as string | undefined) ?? fallback.channelUrl,
      channelAvatarUrl: (data.channelAvatarUrl as string | undefined) ?? "",
      subscribersCount: normalizeNumber(data.subscribersCount) ?? null,
      instanceName:
        (data.instanceName as string | undefined) ?? instanceMeta?.name ?? source.host,
      instanceUrl:
        (data.instanceUrl as string | undefined) ??
        instanceMeta?.url ??
        `https://${source.host}`,
      instanceAvatarUrl: instanceMeta?.avatarUrl ?? "",
      accountName: (data.accountName as string | undefined) ?? "",
      accountUrl: (data.accountUrl as string | undefined) ?? "",
      accountAvatarUrl: (data.accountAvatarUrl as string | undefined) ?? "",
      embedUrl: (data.embedUrl as string | undefined) ?? fallback.embed,
      originalUrl: (data.originalUrl as string | undefined) ?? source.url ?? fallback.url,
      views: normalizeNumber(data.views),
      likes: normalizeNumber(data.likes),
      dislikes: normalizeNumber(data.dislikes),
      description: (data.description as string | undefined) ?? "",
      publishedAt
    };
  } catch {
    return null;
  }
}

/**
 * Handle fetch video metadata from instance.
 */
async function fetchVideoMetadataFromInstance(source: { host: string; id: string; url: string }) {
  try {
    const url = `https://${source.host}/api/v1/videos/${encodeURIComponent(source.id)}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    const channel = (data.channel ?? {}) as Record<string, unknown>;
    const account = (data.account ?? {}) as Record<string, unknown>;
    const channelName =
      (channel.displayName as string | undefined) ??
      (channel.display_name as string | undefined) ??
      (channel.name as string | undefined) ??
      "";
    const channelId = channel.name as string | undefined;
    const channelUrl =
      (channel.url as string | undefined) ??
      (channelId ? `https://${source.host}/video-channels/${encodeURIComponent(channelId)}` : "");
    const channelAvatarUrl =
      resolvePeerTubeAvatarUrl(source.host, channel) ??
      resolvePeerTubeAvatarUrl(source.host, data as Record<string, unknown>) ??
      "";
    const accountName =
      (account.displayName as string | undefined) ??
      (account.display_name as string | undefined) ??
      (account.name as string | undefined) ??
      "";
    const accountUrl = (account.url as string | undefined) ?? "";
    const accountAvatarUrl =
      resolvePeerTubeAvatarUrl(source.host, account) ??
      resolvePeerTubeAvatarUrl(source.host, data as Record<string, unknown>) ??
      "";
    const embedPath = (data.embedPath ?? data.embed_path) as string | undefined;
    const embedUrl = embedPath ? resolveApiAssetUrl(source.host, embedPath) : "";
    const originalUrl =
      (data.url as string | undefined) ??
      (data.videoUrl as string | undefined) ??
      source.url ??
      "";
    const publishedAt = normalizeTimestampMs(data.publishedAt ?? data.published_at);
    const channelMeta = channelId ? await fetchChannelMetadata(source.host, channelId) : null;
    const instanceMeta = await fetchInstanceMetadata(source.host);

    return {
      title: (data.name as string | undefined) ?? (data.title as string | undefined) ?? "",
      channelName: channelName || channelMeta?.displayName || channelMeta?.channelName || "",
      channelUrl: channelMeta?.channelUrl || channelUrl,
      channelAvatarUrl: channelAvatarUrl || channelMeta?.avatarUrl || "",
      subscribersCount: channelMeta?.followersCount ?? null,
      instanceName: instanceMeta?.name ?? source.host,
      instanceUrl: instanceMeta?.url ?? `https://${source.host}`,
      instanceAvatarUrl: instanceMeta?.avatarUrl ?? "",
      accountName,
      accountUrl,
      accountAvatarUrl,
      embedUrl,
      originalUrl,
      views: normalizeNumber(data.views ?? data.viewsCount),
      likes: normalizeNumber(data.likes ?? data.likesCount),
      dislikes: normalizeNumber(data.dislikes ?? data.dislikesCount),
      description: (data.description as string | undefined) ?? "",
      publishedAt
    };
  } catch {
    return null;
  }
}

/**
 * Handle fetch channel metadata.
 */
async function fetchChannelMetadata(host: string, channelId: string) {
  try {
    const url = `https://${host}/api/v1/video-channels/${encodeURIComponent(channelId)}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    return {
      followersCount: normalizeNumber(
        data.followersCount ?? data.followers_count ?? data.followers
      ),
      avatarUrl: resolvePeerTubeAvatarUrl(host, data) ?? "",
      displayName: (data.displayName as string | undefined) ?? (data.display_name as string | undefined) ?? "",
      channelName: (data.name as string | undefined) ?? channelId,
      channelUrl:
        (data.url as string | undefined) ??
        `https://${host}/video-channels/${encodeURIComponent(channelId)}`
    };
  } catch {
    return null;
  }
}

/**
 * Handle fetch instance metadata.
 */
async function fetchInstanceMetadata(host: string) {
  try {
    const url = `https://${host}/api/v1/config`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    const customization = data.customization as Record<string, unknown> | undefined;
    const instance = (data.instance ?? customization?.instance ?? {}) as Record<string, unknown>;
    const branding = (data.branding ?? customization?.branding ?? {}) as Record<string, unknown>;
    const name =
      (getString(instance, ["name", "title", "displayName"]) as string) ??
      (getString(data, ["name", "title"]) as string) ??
      host;
    const avatarUrl =
      resolveAssetCandidate(host, branding.smallLogo) ||
      resolveAssetCandidate(host, branding.logo) ||
      resolveAssetCandidate(host, branding.favicon) ||
      resolveAssetCandidate(host, branding.icon) ||
      resolveAssetCandidate(host, (branding as Record<string, unknown>).small_logo) ||
      resolveAssetCandidate(host, (branding as Record<string, unknown>).logo_url) ||
      resolveAssetCandidate(host, (branding as Record<string, unknown>).favicon_url) ||
      resolveAssetCandidate(host, instance.logo) ||
      resolveAssetCandidate(host, instance.avatars) ||
      resolveAssetCandidate(host, instance.avatar) ||
      `https://${host}/favicon.ico`;
    return {
      name,
      url: `https://${host}`,
      avatarUrl
    };
  } catch {
    return null;
  }
}

/**
 * Handle resolve video source.
 */
function resolveVideoSource() {
  const urlCandidates = [fallback.url, fallback.embed].filter(Boolean);
  const parsed = urlCandidates.map((item) => parseVideoUrl(item)).find((item) => item?.host);
  const host = seedHost ?? parsed?.host ?? "";
  const id = seedId ?? parsed?.id ?? "";
  const url = fallback.url || parsed?.url || "";
  if (!host && !id) return null;
  return { host, id, url };
}

/**
 * Handle parse video url.
 */
function parseVideoUrl(value: string) {
  if (!value) return null;
  try {
    const url = new URL(value);
    const match = url.pathname.match(/\/(?:videos\/watch|videos\/embed|w)\/([^/?#]+)/);
    return {
      host: url.host,
      id: match ? match[1] : "",
      url: value
    };
  } catch {
    return null;
  }
}

/**
 * Handle get string.
 */
function getString(source: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

/**
 * Handle resolve asset candidate.
 */
function resolveAssetCandidate(host: string, value: unknown) {
  if (!value) return "";
  if (typeof value === "string") return resolveApiAssetUrl(host, value);
  if (Array.isArray(value)) {
    for (const item of value) {
      const resolved = resolveAssetCandidate(host, item);
      if (resolved) return resolved;
    }
    return "";
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const path = (obj.path ?? obj.url ?? obj.fileUrl) as string | undefined;
    if (path) return resolveApiAssetUrl(host, path);
  }
  return "";
}

/**
 * Handle resolve peer tube avatar url.
 */
function resolvePeerTubeAvatarUrl(host: string, source: Record<string, unknown>) {
  const avatar = (source.avatar ?? source.channelAvatar ?? source.accountAvatar) as
    | Record<string, unknown>
    | undefined;
  const avatars = (source.avatars ?? source.channelAvatars ?? source.accountAvatars) as
    | Array<Record<string, unknown>>
    | undefined;
  const path =
    (avatar?.path as string | undefined) ??
    (avatar?.url as string | undefined) ??
    (avatars?.[0]?.path as string | undefined) ??
    (avatars?.[0]?.url as string | undefined) ??
    "";
  return path ? resolveApiAssetUrl(host, path) : "";
}

/**
 * Handle resolve api asset url.
 */
function resolveApiAssetUrl(host: string, value: string) {
  if (!value) return "";
  if (value.startsWith("http")) return value;
  return `https://${host}${value.startsWith("/") ? value : `/${value}`}`;
}

/**
 * Handle instance initials.
 */
function instanceInitials(label: string) {
  const trimmed = label.trim();
  if (!trimmed) return "•";
  const cleaned = trimmed.replace(/[_\-]+/g, " ").replace(/\s+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

/**
 * Handle normalize timestamp ms.
 */
function normalizeTimestampMs(value: unknown) {
  if (value == null) return null;
  const raw = Number(value);
  if (!Number.isFinite(raw)) return null;
  if (raw < 1e12) return raw * 1000;
  return raw;
}

/**
 * Handle published at ms.
 */
function publishedAtMs(row: VideoRow) {
  const value = row.published_at ?? row.publishedAt ?? null;
  return normalizeTimestampMs(value);
}

/**
 * Handle normalize number.
 */
function normalizeNumber(value: unknown) {
  if (value == null) return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

/**
 * Handle format time ago.
 */
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

/**
 * Handle format stat value.
 */
function formatStatValue(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return statsNumberFormat.format(value);
}

/**
 * Handle normalize stat value.
 */
function normalizeStatValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

/**
 * Handle resolve similar key.
 */
function resolveSimilarKey(row: VideoRow) {
  const host = row.instance_domain ?? row.instanceDomain ?? "";
  const id = row.video_uuid ?? row.videoUuid ?? row.video_id ?? "";
  if (!host || !id) return null;
  return `${host}::${id}`;
}

/**
 * Handle resolve similar stats.
 */
function resolveSimilarStats(row: VideoRow) {
  const key = resolveSimilarKey(row);
  if (!key) return null;
  if (similarStatsCache.has(key)) {
    return similarStatsCache.get(key) ?? null;
  }
  return normalizeStatValue(row.views ?? row.views_count ?? row.viewsCount) ?? null;
}

/**
 * Check whether has server stats.
 */
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

/**
 * Handle queue similar stats.
 */
function queueSimilarStats(rows: VideoRow[]) {
  if (!rows.length) return;
  const groups = new Map<string, { key: string; id: string }[]>();

  for (const row of rows) {
    const host = row.instance_domain ?? row.instanceDomain ?? "";
    const id = String(row.video_uuid ?? row.videoUuid ?? row.video_id ?? "");
    if (!host || !id) continue;
    const key = `${host}::${id}`;
    if (hasServerStats(row)) {
      if (!similarStatsCache.has(key)) {
        const views = normalizeStatValue(row.views ?? row.views_count ?? row.viewsCount);
        similarStatsCache.set(key, views ?? null);
      }
      continue;
    }
    if (similarStatsCache.has(key)) continue;
    if (similarStatsLoading.has(key)) continue;
    similarStatsLoading.add(key);
    const batch = groups.get(host) ?? [];
    batch.push({ key, id });
    groups.set(host, batch);
  }

  for (const [host, entries] of groups) {
    void fetchSimilarStatsForHost(host, entries);
  }
}

/**
 * Handle fetch similar stats for host.
 */
async function fetchSimilarStatsForHost(host: string, entries: { key: string; id: string }[]) {
  const ids = entries.map((entry) => entry.id);
  try {
    const statsById = await fetchBatchViews(host, ids);
    const missing: { key: string; id: string }[] = [];
    for (const entry of entries) {
      if (!statsById.has(entry.id)) {
        missing.push(entry);
        continue;
      }
      const views = statsById.get(entry.id) ?? null;
      similarStatsCache.set(entry.key, views);
      similarStatsLoading.delete(entry.key);
      applySimilarStatsToDom(entry.key, views);
    }
    if (missing.length) {
      await fetchViewsIndividually(host, missing);
    }
  } catch {
    await fetchViewsIndividually(host, entries);
  }
}

/**
 * Handle fetch views individually.
 */
async function fetchViewsIndividually(host: string, entries: { key: string; id: string }[]) {
  await Promise.all(
    entries.map(async (entry) => {
      try {
        const views = await fetchSingleViews(host, entry.id);
        similarStatsCache.set(entry.key, views);
        applySimilarStatsToDom(entry.key, views);
      } finally {
        similarStatsLoading.delete(entry.key);
      }
    })
  );
}

/**
 * Handle fetch batch views.
 */
async function fetchBatchViews(host: string, ids: string[]) {
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
  const stats = new Map<string, number | null>();
  for (const item of data) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const uuid = record.uuid ?? record.video_uuid ?? record.videoUuid;
    const id = record.id ?? record.video_id ?? record.videoId;
    const views = normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
    if (uuid) stats.set(String(uuid), views);
    if (id) stats.set(String(id), views);
  }
  return stats;
}

/**
 * Handle fetch single views.
 */
async function fetchSingleViews(host: string, id: string) {
  const url = `https://${host}/api/v1/videos/${encodeURIComponent(id)}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) return null;
  const record = (await response.json()) as Record<string, unknown>;
  return normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
}

/**
 * Handle apply similar stats to dom.
 */
function applySimilarStatsToDom(key: string, views: number | null) {
  if (!similarCards) return;
  const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(key) : key;
  const card = similarCards.querySelector<HTMLElement>(`[data-video-key="${escaped}"]`);
  if (!card) return;
  const viewsEl = card.querySelector<HTMLElement>('[data-stat="views"]');
  if (viewsEl) viewsEl.textContent = formatStatValue(views);
}

/**
 * Handle embed url for.
 */
function embedUrlFor(row: VideoRow | null) {
  if (!row) return "";
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

/**
 * Handle video url for.
 */
function videoUrlFor(row: VideoRow | null) {
  if (!row) return "";
  if (row.video_url) return row.video_url;
  if (row.videoUrl) return row.videoUrl;
  const uuid = row.video_uuid;
  const host = row.instance_domain ?? row.instanceDomain;
  if (uuid && host) {
    return `https://${host}/videos/watch/${encodeURIComponent(uuid)}`;
  }
  return "";
}

/**
 * Handle video page url.
 */
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
  const channelHref = channelUrlFor(row);
  if (channelHref) params.set("channelUrl", channelHref);
  const embed = embedUrlFor(row);
  if (embed) params.set("embed", embed);
  const original = videoUrlFor(row);
  if (original) params.set("url", original);
  return `/video-page.html?${params.toString()}`;
}

/**
 * Handle thumbnail url.
 */
function thumbnailUrl(row: VideoRow) {
  return row.thumbnail_url ?? row.thumbnailUrl ?? row.preview_path ?? row.previewPath ?? null;
}

/**
 * Handle render similar card.
 */
function renderSimilarCard(row: VideoRow) {
  const title = row.title ?? "Untitled video";
  const thumb = thumbnailUrl(row);
  const duration = formatDuration(row.duration ?? null);
  const channel = channelName(row) ?? "Unknown channel";
  const key = resolveSimilarKey(row);
  const views = resolveSimilarStats(row);
  const publishedAt = publishedAtMs(row);
  const timeAgo = publishedAt ? formatTimeAgo(publishedAt) : null;
  const timeSuffix = timeAgo ? ` · ${timeAgo}` : "";
  const thumbMarkup = thumb
    ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
    : "";
  const keyAttribute = key ? ` data-video-key="${escapeHtml(key)}"` : "";
  return `
    <a class="similar-card-item" href="${escapeHtml(videoPageUrl(row))}"${keyAttribute}>
      <div class="similar-thumb">
        ${thumbMarkup}
        <span class="duration">${escapeHtml(duration)}</span>
      </div>
      <h4 class="similar-title">${escapeHtml(title)}</h4>
      <p class="similar-channel">${escapeHtml(channel)}</p>
      <p class="similar-meta"><span data-stat="views">${formatStatValue(views)}</span> views${escapeHtml(timeSuffix)}</p>
    </a>
  `;
}

/**
 * Handle format duration.
 */
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

/**
 * Handle toggle reaction.
 */
function toggleReaction(active: HTMLButtonElement, other: HTMLButtonElement) {
  const wasActive = active.classList.contains("active");
  active.classList.toggle("active", !wasActive);
  if (!wasActive) {
    other.classList.remove("active");
  }
  return !wasActive;
}

/**
 * Handle handle like action.
 */
async function handleLikeAction() {
  if (!seedId) return;
  if (!(likeButton instanceof HTMLButtonElement)) return;
  likeButton.disabled = true;
  try {
    await sendUserAction(apiBase, {
      videoId: seedId,
      host: seedHost,
      action: "like"
    });
  } catch (error) {
    console.warn("[video] failed to send action", error);
  } finally {
    const uuid = resolveLikeUuid(seedId, currentMetadata);
    const host = resolveLikeHost(seedHost, currentMetadata);
    if (uuid && host) {
      addLocalLike(uuid, host);
    }
    likeButton.disabled = false;
  }
}

/**
 * Handle resolve like uuid.
 */
function resolveLikeUuid(id: string, metadata: VideoMetadata | null) {
  const candidate = metadata?.videoUuid ?? "";
  if (candidate) return candidate;
  return looksLikeUuid(id) ? id : "";
}

/**
 * Handle resolve like host.
 */
function resolveLikeHost(hostParam: string | null, metadata: VideoMetadata | null) {
  const host = hostParam?.trim();
  if (host) return host;
  const metaHost = metadata?.instanceName?.trim();
  if (metaHost) return metaHost;
  return "";
}

/**
 * Handle looks like uuid.
 */
function looksLikeUuid(value: string) {
  return /^[0-9a-fA-F-]{32,36}$/.test(value);
}

/**
 * Handle number format.
 */
function numberFormat() {
  return new Intl.NumberFormat("en-US");
}

/**
 * Handle icon eye.
 */
function iconEye() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="3.2" />
    </svg>
  `;
}

/**
 * Handle icon thumb up.
 */
function iconThumbUp() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

/**
 * Handle icon thumb down.
 */
function iconThumbDown() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

/**
 * Handle apply action icons.
 */
function applyActionIcons() {
  if (likeButton instanceof HTMLButtonElement) {
    likeButton.insertAdjacentHTML("afterbegin", iconThumbUp());
  }
  if (dislikeButton instanceof HTMLButtonElement) {
    dislikeButton.insertAdjacentHTML("afterbegin", iconThumbDown());
  }
}

applyActionIcons();

/**
 * Handle escape html.
 */
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
