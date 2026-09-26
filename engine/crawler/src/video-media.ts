/**
 * Media-selection helpers for PeerTube video payloads.
 *
 * The crawler receives media fields from list/detail payloads in multiple
 * PeerTube versions. These helpers centralize canonical absolute-URL and
 * thumbnail-dimension selection so persistence does not depend on wire shape.
 */

interface PeerTubeAssetLike {
  fileUrl?: unknown;
  url?: unknown;
  path?: unknown;
  staticPath?: unknown;
  width?: unknown;
  height?: unknown;
}

export interface PeerTubeVideoMediaLike {
  thumbnails?: unknown;
  thumbnailUrl?: unknown;
  thumbnailPath?: unknown;
  thumbnail_path?: unknown;
  thumbnail?: unknown;
  previewUrl?: unknown;
  preview_url?: unknown;
  previewPath?: unknown;
  preview_path?: unknown;
}

export interface ResolvedThumbnail {
  url: string | null;
  width: number | null;
  height: number | null;
}

/** Resolve one PeerTube asset field into an absolute URL when possible. */
export function resolvePeerTubeMediaUrl(
  value: unknown,
  host: string,
  protocol: string
): string | null {
  const candidate = extractAssetValue(value);
  if (!candidate) return null;
  if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
    return candidate;
  }
  if (candidate.startsWith("/")) {
    return `${protocol}//${host}${candidate}`;
  }
  return `${protocol}//${host}/${candidate}`;
}

/**
 * Select one canonical thumbnail with dimensions.
 *
 * Modern detail thumbnails have first priority and use the largest known pixel
 * area; source order breaks ties. Legacy fields remain as compatibility
 * fallbacks and preview media is deliberately last because it is not always a
 * card thumbnail.
 */
export function resolvePreferredThumbnail(
  detail: PeerTubeVideoMediaLike | null,
  listVideo: PeerTubeVideoMediaLike,
  host: string,
  protocol: string
): ResolvedThumbnail {
  const detailModern = selectModernThumbnail(detail?.thumbnails, host, protocol);
  if (detailModern.url) return detailModern;

  const detailLegacy = resolveFirstLegacyThumbnail(detail, host, protocol);
  if (detailLegacy.url) return detailLegacy;

  const listModern = selectModernThumbnail(listVideo.thumbnails, host, protocol);
  if (listModern.url) return listModern;

  const listLegacy = resolveFirstLegacyThumbnail(listVideo, host, protocol);
  if (listLegacy.url) return listLegacy;

  // Preview fields remain a final compatibility fallback only.
  const previewCandidates = [
    detail?.previewUrl,
    detail?.preview_url,
    detail?.previewPath,
    detail?.preview_path,
    listVideo.previewUrl,
    listVideo.preview_url,
    listVideo.previewPath,
    listVideo.preview_path
  ];
  for (const candidate of previewCandidates) {
    const url = resolvePeerTubeMediaUrl(candidate, host, protocol);
    if (url) return { url, width: null, height: null };
  }
  return { url: null, width: null, height: null };
}

/** Preserve the URL-only contract used by thumbnail maintenance callers. */
export function resolvePreferredThumbnailUrl(
  detail: PeerTubeVideoMediaLike | null,
  listVideo: PeerTubeVideoMediaLike,
  host: string,
  protocol: string
): string | null {
  return resolvePreferredThumbnail(detail, listVideo, host, protocol).url;
}

/** Prefer fresher preview path fields while preserving relative-path storage. */
export function resolvePreferredPreviewPath(
  detail: PeerTubeVideoMediaLike | null,
  listVideo: PeerTubeVideoMediaLike
): string | null {
  return toNullableString(
    detail?.previewPath ??
      detail?.preview_path ??
      listVideo.previewPath ??
      listVideo.preview_path
  );
}

/** Pick the largest valid modern thumbnail, preserving source order on ties. */
function selectModernThumbnail(
  value: unknown,
  host: string,
  protocol: string
): ResolvedThumbnail {
  if (!Array.isArray(value)) return { url: null, width: null, height: null };
  let best: ResolvedThumbnail | null = null;
  let bestArea = -1;
  for (const candidate of value) {
    if (!candidate || typeof candidate !== "object") continue;
    const asset = candidate as PeerTubeAssetLike;
    const url = resolvePeerTubeMediaUrl(asset, host, protocol);
    if (!url) continue;
    const width = toNullableNumber(asset.width);
    const height = toNullableNumber(asset.height);
    const area = width !== null && height !== null ? width * height : 0;
    if (!best || area > bestArea) {
      best = { url, width, height };
      bestArea = area;
    }
  }
  return best ?? { url: null, width: null, height: null };
}

/** Resolve legacy thumbnail fields without considering preview fallbacks. */
function resolveFirstLegacyThumbnail(
  source: PeerTubeVideoMediaLike | null,
  host: string,
  protocol: string
): ResolvedThumbnail {
  const candidates = [
    source?.thumbnailPath,
    source?.thumbnailUrl,
    source?.thumbnail_path,
    source?.thumbnail
  ];
  for (const candidate of candidates) {
    const url = resolvePeerTubeMediaUrl(candidate, host, protocol);
    if (url) return { url, width: null, height: null };
  }
  return { url: null, width: null, height: null };
}

/** Extract the underlying asset path or URL from mixed PeerTube field shapes. */
function extractAssetValue(value: unknown): string | null {
  if (typeof value === "string" && value.length > 0) return value;
  if (value && typeof value === "object") {
    const asset = value as PeerTubeAssetLike;
    return (
      toNullableString(asset.fileUrl) ??
      toNullableString(asset.url) ??
      toNullableString(asset.path) ??
      toNullableString(asset.staticPath)
    );
  }
  return null;
}

/** Normalize dimensions from current PeerTube numeric fields. */
function toNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Collapse blank strings to null so storage logic keeps nullable semantics. */
function toNullableString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}
