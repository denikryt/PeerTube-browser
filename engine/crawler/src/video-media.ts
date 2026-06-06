/**
 * Media-selection helpers for PeerTube video payloads.
 *
 * The crawler receives media fields from both channel-list payloads and
 * per-video detail payloads. These helpers centralize the precedence rules so
 * normal crawls can prefer fresher detail media without duplicating URL logic.
 */

interface PeerTubeAssetLike {
  url?: unknown;
  path?: unknown;
  staticPath?: unknown;
}

export interface PeerTubeVideoMediaLike {
  thumbnailUrl?: unknown;
  thumbnailPath?: unknown;
  thumbnail_path?: unknown;
  thumbnail?: unknown;
  previewUrl?: unknown;
  previewPath?: unknown;
  preview_path?: unknown;
}

/**
 * Resolve one PeerTube asset field into an absolute URL when possible.
 */
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
 * Prefer fresher thumbnail fields from detail payloads and fall back to list
 * payloads only when detail media is absent.
 */
export function resolvePreferredThumbnailUrl(
  detail: PeerTubeVideoMediaLike | null,
  listVideo: PeerTubeVideoMediaLike,
  host: string,
  protocol: string
): string | null {
  const candidates = [
    detail?.thumbnailPath,
    detail?.previewPath,
    detail?.preview_path,
    detail?.thumbnailUrl,
    detail?.thumbnail_path,
    detail?.thumbnail,
    listVideo.thumbnailPath,
    listVideo.thumbnailUrl,
    listVideo.thumbnail_path,
    listVideo.thumbnail,
    listVideo.previewPath,
    listVideo.preview_path
  ];

  for (const candidate of candidates) {
    const resolved = resolvePeerTubeMediaUrl(candidate, host, protocol);
    if (resolved) return resolved;
  }
  return null;
}

/**
 * Prefer fresher preview path fields from detail payloads while preserving the
 * existing stored shape as a relative path when PeerTube provides one.
 */
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

/**
 * Extract the underlying asset path or URL from mixed PeerTube field shapes.
 */
function extractAssetValue(value: unknown): string | null {
  if (typeof value === "string" && value.length > 0) return value;
  if (value && typeof value === "object") {
    const asset = value as PeerTubeAssetLike;
    return (
      toNullableString(asset.url) ??
      toNullableString(asset.path) ??
      toNullableString(asset.staticPath)
    );
  }
  return null;
}

/**
 * Collapse blank strings to null so storage logic keeps nullable semantics.
 */
function toNullableString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}
