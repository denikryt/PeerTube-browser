/**
 * PeerTube video media URL helpers.
 *
 * The crawler uses these helpers to turn PeerTube list/detail payload fields
 * into one absolute browser-safe image URL. The ordering prefers canonical
 * live-detail fields so stale list URLs do not persist in SQLite.
 */

export interface PeerTubeMediaSource {
  thumbnailUrl?: unknown;
  thumbnailPath?: unknown;
  thumbnail_path?: unknown;
  thumbnail?: unknown;
  previewPath?: unknown;
  preview_path?: unknown;
  previewUrl?: unknown;
  preview_url?: unknown;
}

interface PeerTubeAsset {
  url?: unknown;
  path?: unknown;
  staticPath?: unknown;
}

interface ThumbnailCandidate {
  field: string;
  value: string;
  url: string;
}

/**
 * Return a normalized non-empty string or ``null``.
 */
function toText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text.length > 0 ? text : null;
}

/**
 * Extract a path-like asset value from a PeerTube payload field.
 */
function extractAssetValue(value: unknown): string | null {
  if (typeof value === "string") return toText(value);
  if (!value || typeof value !== "object") return null;
  const asset = value as PeerTubeAsset;
  return toText(asset.url ?? asset.path ?? asset.staticPath);
}

/**
 * Resolve one PeerTube asset value into an absolute browser-safe URL.
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
 * Build the ordered thumbnail candidates for one PeerTube media payload.
 *
 * Live-detail paths are preferred over list payload URLs because list payloads
 * can lag behind the current asset set for the same video.
 */
export function buildThumbnailCandidates(
  source: PeerTubeMediaSource,
  host: string,
  protocol: string
): ThumbnailCandidate[] {
  const orderedFields: Array<[string, unknown]> = [
    ["thumbnailPath", source.thumbnailPath],
    ["previewPath", source.previewPath],
    ["thumbnailUrl", source.thumbnailUrl],
    ["previewUrl", source.previewUrl],
    ["thumbnail_path", source.thumbnail_path],
    ["preview_path", source.preview_path],
    ["thumbnail", source.thumbnail]
  ];
  const candidates: ThumbnailCandidate[] = [];
  for (const [field, value] of orderedFields) {
    const url = resolvePeerTubeMediaUrl(value, host, protocol);
    if (!url) continue;
    const text = toText(value);
    if (!text) continue;
    candidates.push({ field, value: text, url });
  }
  return candidates;
}

/**
 * Resolve the best browser-visible thumbnail URL from a PeerTube payload.
 */
export function resolvePreferredThumbnailUrl(
  source: PeerTubeMediaSource,
  host: string,
  protocol: string
): string | null {
  return buildThumbnailCandidates(source, host, protocol)[0]?.url ?? null;
}
