/**
 * Video-row field resolution helpers shared by feed and video-detail renderers.
 */

import type { ThumbnailCandidate, VideoRow } from "../types/videos";

/** Resolve the current instance-domain compatibility aliases used by API rows. */
export function resolveInstanceDomain(row: VideoRow | null) {
  return row?.instance_domain ?? row?.instanceDomain ?? "";
}

/** Resolve the current video identity preference used by live stats and links. */
export function resolveVideoId(row: VideoRow | null) {
  const value = row?.video_uuid ?? row?.videoUuid ?? row?.video_id ?? "";
  return value ? String(value) : "";
}

/** Resolve the DOM/live-stats key without changing the existing host/id delimiter. */
export function resolveVideoKey(row: VideoRow | null) {
  const host = resolveInstanceDomain(row);
  const id = resolveVideoId(row);
  if (!host || !id) return null;
  return `${host}::${id}`;
}

/** Return the stable feed/search row identity used by duplicate guards and Vue keys. */
export function videoRowKey(row: VideoRow | null) {
  const host = resolveInstanceDomain(row);
  const id = resolveVideoId(row) || (row?.video_numeric_id != null ? String(row.video_numeric_id) : "");
  return `${host}::${id}`;
}

/** Return the first occurrence of each stable video-row identity. */
export function dedupeVideoRows(rows: VideoRow[]) {
  const result: VideoRow[] = [];
  appendUniqueVideoRows(result, rows);
  return result;
}

/** Append only rows whose stable identity is not already present in the target. */
export function appendUniqueVideoRows(target: VideoRow[], rows: VideoRow[]) {
  const seen = new Set(target.map(videoRowKey));
  for (const row of rows) {
    const key = videoRowKey(row);
    if (seen.has(key)) continue;
    seen.add(key);
    target.push(row);
  }
}

/** Keep only an optional positive pixel dimension from a Client API candidate. */
function thumbnailDimension(value: unknown) {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

/** Resolve ordered Client API candidate objects without using preview fields. */
export function thumbnailCandidates(row: VideoRow): ThumbnailCandidate[] {
  const explicitCandidates = row.thumbnail_candidates ?? row.thumbnailCandidates;
  if (Array.isArray(explicitCandidates)) {
    const seen = new Set<string>();
    const candidates: ThumbnailCandidate[] = [];
    for (const value of explicitCandidates) {
      if (!value || typeof value !== "object" || !("url" in value)) continue;
      const url = value.url;
      if (typeof url !== "string") continue;
      const normalized = url.trim();
      if (!normalized || seen.has(normalized)) continue;
      seen.add(normalized);
      candidates.push({
        url: normalized,
        width: thumbnailDimension(value.width),
        height: thumbnailDimension(value.height)
      });
    }
    return candidates;
  }

  const explicit = row.thumbnail_urls ?? row.thumbnailUrls;
  if (Array.isArray(explicit)) {
    const seen = new Set<string>();
    const candidates: ThumbnailCandidate[] = [];
    for (const value of explicit) {
      if (typeof value !== "string") continue;
      const normalized = value.trim();
      if (!normalized || seen.has(normalized)) continue;
      seen.add(normalized);
      candidates.push({ url: normalized, width: null, height: null });
    }
    return candidates;
  }

  const singular = row.thumbnail_url ?? row.thumbnailUrl ?? null;
  if (typeof singular !== "string") return [];
  const normalized = singular.trim();
  return normalized ? [{ url: normalized, width: null, height: null }] : [];
}

/** Resolve ordered Client API thumbnail URLs for callers that only need compatibility fields. */
export function thumbnailUrls(row: VideoRow) {
  return thumbnailCandidates(row).map((candidate) => candidate.url);
}

/** Resolve the first canonical Client API thumbnail candidate for compatibility callers. */
export function thumbnailUrl(row: VideoRow) {
  return thumbnailUrls(row)[0] ?? null;
}

/** Resolve the current channel display label aliases. */
export function channelName(row: VideoRow | null) {
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

/** Resolve initials for avatar fallback badges with the current punctuation cleanup. */
export function channelInitials(row: VideoRow | null) {
  const label = (channelName(row) || "Unknown channel").trim();
  if (!label) return "•";
  const cleaned = label.replace(/[_\-]+/g, " ").replace(/\s+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

/** Resolve current avatar aliases used by feed cards. */
export function channelAvatarUrl(row: VideoRow) {
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

/** Resolve current channel URL fallback. */
export function channelUrl(row: VideoRow | null) {
  if (row?.channel_url) return row.channel_url;
  if (row?.channelUrl) return row.channelUrl;
  const name = row?.channel_name ?? row?.channelName;
  const host = row?.instance_domain ?? row?.instanceDomain;
  if (name && host) {
    return `https://${host}/video-channels/${encodeURIComponent(name)}`;
  }
  return "#";
}

/** Resolve current original video URL fallback. */
export function videoUrl(row: VideoRow | null) {
  if (row?.video_url) return row.video_url;
  if (row?.videoUrl) return row.videoUrl;
  const uuid = row?.video_uuid ?? row?.videoUuid;
  const host = row?.instance_domain ?? row?.instanceDomain;
  if (uuid && host) {
    return `https://${host}/videos/watch/${encodeURIComponent(uuid)}`;
  }
  return "#";
}

/** Resolve current embed URL fallback. */
export function embedUrl(row: VideoRow | null) {
  const raw = row?.embed_path ?? row?.embedPath ?? "";
  if (raw.startsWith("http")) return raw;
  const host = row?.instance_domain ?? row?.instanceDomain;
  if (raw && host) {
    return `https://${host}${raw}`;
  }
  const uuid = row?.video_uuid ?? row?.videoUuid;
  if (uuid && host) {
    return `https://${host}/videos/embed/${encodeURIComponent(uuid)}`;
  }
  return "";
}

/** Resolve the current epoch-seconds-or-ms published timestamp compatibility. */
export function publishedAtMs(row: VideoRow | null) {
  const raw = row?.published_at ?? row?.publishedAt ?? null;
  if (!raw || !Number.isFinite(raw)) return null;
  const value = Number(raw);
  if (value < 1e12) return value * 1000;
  return value;
}

/** Build canonical Vue Router video detail links from stable host-scoped identity. */
export function videoPageUrl(row: VideoRow, _apiParam?: string | null) {
  const host = encodeURIComponent(resolveInstanceDomain(row));
  const id = encodeURIComponent(resolveVideoId(row));
  if (!host || !id) return "/video";
  return `/video/${host}/${id}`;
}

/** Check whether server-provided rows already include usable stat fields. */
export function hasServerStats(row: VideoRow) {
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
