/**
 * Video card renderers extracted from the existing feed and video-page modules.
 */

import type { VideoRow } from "../types/videos";
import { iconThumbDown, iconThumbUp } from "./icons";
import { escapeHtml, formatDebugInt, formatDebugNumber, formatDuration, formatStatValue, formatTimeAgo, normalizeStatValue } from "../utils/format";
import { channelAvatarUrl, channelInitials, channelName, channelUrl, hasServerStats, publishedAtMs, thumbnailUrl, videoPageUrl } from "../utils/video-fields";

export type VideoStats = {
  views: number | null;
  likes: number | null;
  dislikes: number | null;
};

export type FeedVideoCardOptions = {
  apiParam?: string | null;
  debugMode?: boolean;
  stats?: VideoStats | null;
  videoKey?: string | null;
};

/** Render the existing feed card markup while keeping CSS classes and data attributes stable. */
export function renderFeedVideoCard(row: VideoRow, options: FeedVideoCardOptions = {}) {
  const title = row.title ?? "Untitled video";
  const thumb = thumbnailUrl(row);
  const duration = formatDuration(row.duration ?? null);
  const stats = options.stats ?? (hasServerStats(row) ? resolveServerStats(row) : null);
  const views = stats?.views ?? null;
  const likes = stats?.likes ?? null;
  const dislikes = stats?.dislikes ?? null;
  const channelLabel = channelName(row) || "Unknown channel";
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
  const keyAttribute = options.videoKey ? ` data-video-key="${escapeHtml(options.videoKey)}"` : "";
  const debugMarkup = renderDebugMetrics(row, Boolean(options.debugMode));

  return `
    <article class="video-card"${keyAttribute}>
      <a class="video-link" href="${escapeHtml(videoPageUrl(row, options.apiParam))}">
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

export type SimilarVideoCardOptions = {
  apiParam?: string | null;
  views?: number | null;
  videoKey?: string | null;
};

/** Render the existing similar-card markup from the video detail page. */
export function renderSimilarVideoCard(row: VideoRow, options: SimilarVideoCardOptions = {}) {
  const title = row.title ?? "Untitled video";
  const thumb = thumbnailUrl(row);
  const duration = formatDuration(row.duration ?? null);
  const channel = channelName(row) || "Unknown channel";
  const views = options.views ?? resolveSimilarViews(row);
  const publishedAt = publishedAtMs(row);
  const timeAgo = publishedAt ? formatTimeAgo(publishedAt) : null;
  const timeSuffix = timeAgo ? ` · ${timeAgo}` : "";
  const thumbMarkup = thumb
    ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
    : "";
  const keyAttribute = options.videoKey ? ` data-video-key="${escapeHtml(options.videoKey)}"` : "";
  return `
    <a class="similar-card-item" href="${escapeHtml(videoPageUrl(row, options.apiParam))}"${keyAttribute}>
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

/** Resolve current server stat aliases for feed card rendering. */
export function resolveServerStats(row: VideoRow): VideoStats {
  return {
    views: normalizeStatValue(row.views ?? row.viewsCount),
    likes: normalizeStatValue(row.likes ?? row.likes_count),
    dislikes: normalizeStatValue(row.dislikes ?? row.dislikes_count)
  };
}

/** Resolve the current similar-card view-only stat aliases. */
export function resolveSimilarViews(row: VideoRow) {
  return normalizeStatValue(row.views ?? row.viewsCount);
}

/** Render current recommendation debug fields only when debug mode is active. */
function renderDebugMetrics(row: VideoRow, debugMode: boolean) {
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
