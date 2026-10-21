/**
 * Video-row field resolution helpers shared by feed and video-detail renderers.
 */

import type { VideoRow } from "../types/videos";

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

/** Resolve the current thumbnail/preview aliases. */
export function thumbnailUrl(row: VideoRow) {
  return row.thumbnail_url ?? row.thumbnailUrl ?? row.preview_path ?? row.previewPath ?? null;
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

/** Build current video detail page links while preserving optional api forwarding. */
export function videoPageUrl(row: VideoRow, apiParam?: string | null) {
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
