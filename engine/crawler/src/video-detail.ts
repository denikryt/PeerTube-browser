/** Canonical side-effect-free PeerTube direct-video-detail request boundary. */

import { classifyCrawlError, shouldTryAlternateProtocol, type CrawlErrorClassification } from "./error-classification.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import type { RequestLimiter } from "./request-limiter.js";

/** Request settings owned by the existing crawler HTTP retry layer. */
export interface VideoDetailRequestOptions {
  timeoutMs: number;
  maxRetries: number;
}

/** Diagnostic facts for an uncertain detail observation. */
export interface VideoDetailFailure {
  message: string;
  classification: CrawlErrorClassification;
  cause: unknown;
}

/** Final outcome of one logical `(instance, uuid)` detail operation. */
export type VideoDetailResult<TDetail extends Record<string, unknown>> =
  | { kind: "available"; detail: TDetail; protocol: string; checkedAt: number }
  | { kind: "not_found"; checkedAt: number }
  | { kind: "gone"; checkedAt: number }
  | { kind: "unknown"; error: VideoDetailFailure; checkedAt: number };

interface VideoDetailFetchResult<TDetail extends Record<string, unknown>> {
  detail: TDetail;
  protocol: string;
}

/** Build the PeerTube REST detail URL for one exact UUID identity. */
function buildVideoDetailUrl(host: string, videoUuid: string, protocol: string): string {
  return `${protocol}//${host}/api/v1/videos/${encodeURIComponent(videoUuid)}`;
}

/**
 * Validate only the minimum wire contract needed to bind payload identity.
 * Complete PeerTube payload decoding remains the responsibility of projections.
 */
function validateVideoDetailIdentity(
  value: unknown,
  requestedUuid: string
): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid video detail payload");
  }
  const record = value as Record<string, unknown>;
  if (typeof record.uuid !== "string" || record.uuid.length === 0 || record.uuid !== requestedUuid) {
    // Untrusted payload fields never become trusted identity or diagnostic text.
    throw new Error("invalid video detail identity");
  }
  return record;
}

/** Perform one primary request plus the existing eligible protocol fallback. */
async function fetchVideoDetailInternal<TDetail extends Record<string, unknown>>(
  host: string,
  videoUuid: string,
  options: VideoDetailRequestOptions,
  protocol: string,
  requestLimiter: RequestLimiter
): Promise<VideoDetailFetchResult<TDetail>> {
  const request = async (requestProtocol: string, maxRetries: number) => {
    const url = buildVideoDetailUrl(host, videoUuid, requestProtocol);
    const payload = await requestLimiter.run(() =>
      fetchJsonWithRetry<unknown>(url, {
        timeoutMs: options.timeoutMs,
        maxRetries
      })
    );
    return validateVideoDetailIdentity(payload, videoUuid) as TDetail;
  };

  try {
    return {
      detail: await request(protocol, options.maxRetries),
      protocol
    };
  } catch (error) {
    // Semantic-invalid 2xx validation errors classify as unknown and therefore
    // do not become an accidental reason to retry over another protocol.
    // An explicit local outage has priority over message-based protocol fallback.
    if (isNoNetworkError(error) || !shouldTryAlternateProtocol(error)) throw error;
    const fallbackProtocol = protocol === "https:" ? "http:" : "https:";
    return {
      detail: await request(fallbackProtocol, Math.max(1, Math.floor(options.maxRetries / 2))),
      protocol: fallbackProtocol
    };
  }
}

/** Return exactly one explicit result for one logical video-detail operation. */
export async function fetchVideoDetailResult<TDetail extends Record<string, unknown>>(
  host: string,
  videoUuid: string,
  options: VideoDetailRequestOptions,
  protocol: string,
  requestLimiter: RequestLimiter
): Promise<VideoDetailResult<TDetail>> {
  try {
    const result = await fetchVideoDetailInternal<TDetail>(
      host,
      videoUuid,
      options,
      protocol,
      requestLimiter
    );
    return { kind: "available", ...result, checkedAt: Date.now() };
  } catch (error) {
    // Explicit local outage is process-fatal, not an unknown remote video.
    if (isNoNetworkError(error)) throw error;
    const classification = classifyCrawlError(error);
    const checkedAt = Date.now();
    if (classification.httpStatus === 404) return { kind: "not_found", checkedAt };
    if (classification.httpStatus === 410) return { kind: "gone", checkedAt };
    return {
      kind: "unknown",
      error: {
        message: error instanceof Error ? error.message : String(error),
        classification,
        cause: error
      },
      checkedAt
    };
  }
}
