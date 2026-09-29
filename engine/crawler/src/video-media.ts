/**
 * Media-selection helpers for PeerTube video payloads.
 *
 * Modern REST thumbnail arrays are the authoritative candidate source. Legacy
 * thumbnail fields remain a singular compatibility source, while preview media
 * is intentionally kept separate from card-thumbnail fallback semantics.
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

export interface ThumbnailCandidate {
  url: string;
  width: number | null;
  height: number | null;
}

export interface ResolvedThumbnail {
  url: string | null;
  width: number | null;
  height: number | null;
}

/** Resolve one PeerTube asset field into an absolute HTTP(S) URL when possible. */
export function resolvePeerTubeMediaUrl(
  value: unknown,
  host: string,
  protocol: string
): string | null {
  const candidate = extractAssetValue(value);
  if (!candidate) return null;

  const explicitScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:/u.test(candidate);
  if (explicitScheme) {
    if (!/^https?:\/\//iu.test(candidate)) return null;
    try {
      const parsed = new URL(candidate);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? candidate : null;
    } catch {
      return null;
    }
  }

  const baseProtocol = protocol === "http:" ? "http:" : "https:";
  if (candidate.startsWith("/")) {
    return `${baseProtocol}//${host}${candidate}`;
  }
  return `${baseProtocol}//${host}/${candidate}`;
}

/**
 * Normalize an actual PeerTube REST `thumbnails` array into ordered candidates.
 *
 * `null` is deliberately distinct from `[]`: null means the modern source was
 * absent/non-array, while an empty array is an authoritative empty candidate set.
 */
export function resolveThumbnailCandidates(
  thumbnails: unknown,
  host: string,
  protocol: string
): ThumbnailCandidate[] | null {
  if (!Array.isArray(thumbnails)) return null;

  const candidates: ThumbnailCandidate[] = [];
  for (const value of thumbnails) {
    if (!value || typeof value !== "object") continue;
    const asset = value as PeerTubeAssetLike;
    const url = resolvePeerTubeMediaUrl(asset, host, protocol);
    if (!url) continue;
    candidates.push({
      url,
      width: toThumbnailDimension(asset.width),
      height: toThumbnailDimension(asset.height)
    });
  }

  // ES2019+ sort is stable, so equal/unknown areas retain PeerTube REST order.
  const area = (candidate: ThumbnailCandidate) =>
    candidate.width !== null && candidate.height !== null
      ? candidate.width * candidate.height
      : -1;
  candidates.sort((left, right) => area(right) - area(left));

  const seen = new Set<string>();
  const deduplicated: ThumbnailCandidate[] = [];
  for (const candidate of candidates) {
    if (seen.has(candidate.url)) continue;
    seen.add(candidate.url);
    deduplicated.push(candidate);
  }
  return deduplicated;
}

/**
 * Resolve only the legacy singular compatibility thumbnail.
 *
 * Detail legacy fields win, followed by list modern candidates and list legacy
 * fields. Preview fields are intentionally excluded from this compatibility path.
 */
export function resolveLegacyThumbnailCompatibility(
  detail: PeerTubeVideoMediaLike | null,
  listVideo: PeerTubeVideoMediaLike,
  host: string,
  protocol: string
): ResolvedThumbnail {
  const detailLegacy = resolveFirstLegacyThumbnail(detail, host, protocol);
  if (detailLegacy.url) return detailLegacy;

  const listModern = resolveThumbnailCandidates(listVideo.thumbnails, host, protocol);
  if (listModern && listModern.length > 0) return listModern[0];

  return resolveFirstLegacyThumbnail(listVideo, host, protocol);
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
  if (typeof value === "string") return toNullableString(value);
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

/** Keep only positive finite integer dimensions used by PeerTube thumbnail sizing. */
function toThumbnailDimension(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value > 0
    ? value
    : null;
}

/** Collapse blank strings to null so storage logic keeps nullable semantics. */
function toNullableString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}
