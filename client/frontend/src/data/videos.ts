/**
 * Module `client/frontend/src/data/videos.ts`: provide runtime functionality.
 */

import type { DiscoveryListPayload, VideoRow, VideosPayload } from "../types/videos";
import { fetchJsonWithCache } from "./cache";
import { resolveClientApiBase } from "./api-base";

export interface SimilarQuery {
  id?: string | null;
  host?: string | null;
  limit?: string | null;
  apiBase?: string | null;
  random?: string | null;
  debug?: string | null;
  cursor?: string | null;
}

const STATIC_VIDEO_URLS = ["/videos.json", "./videos.json", "videos.json"];

/**
 * Handle parse similar query.
 */
export function parseSimilarQuery(params: URLSearchParams): SimilarQuery {
  return {
    id: params.get("id"),
    host: params.get("host"),
    limit: params.get("limit"),
    apiBase: params.get("api"),
    random: params.get("random"),
    debug: params.get("debug"),
    cursor: params.get("cursor")
  };
}

/**
 * Handle resolve api base.
 */
export function resolveApiBase(query: SimilarQuery) {
  return resolveClientApiBase(query.apiBase);
}

/**
 * Handle build similar url.
 */
export function buildSimilarUrl(query: SimilarQuery) {
  const apiBase = resolveApiBase(query);
  const path = query.id
    ? `/api/v1/videos/${encodeURIComponent(query.id)}/similar`
    : query.random
      ? "/api/v1/discovery/random"
      : "/api/v1/discovery/recommendations";
  const url = new URL(path, apiBase);
  if (query.host) url.searchParams.set("host", query.host);
  if (query.limit) url.searchParams.set("limit", query.limit);
  if (query.cursor) url.searchParams.set("cursor", query.cursor);
  if (query.debug) url.searchParams.set("debug", query.debug);
  return url.toString();
}

/**
 * Handle fetch static videos payload.
 */
export async function fetchStaticVideosPayload(options: { cacheTtlMs?: number } = {}) {
  let lastError: string | null = null;
  for (const url of STATIC_VIDEO_URLS) {
    try {
      return await fetchJsonWithCache<VideosPayload | VideoRow[]>(url, {
        cacheKey: `videos:${url}`,
        ttlMs: options.cacheTtlMs ?? 0
      });
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
  }
  throw new Error(lastError ?? "Failed to load videos.json");
}

/**
 * Handle fetch similar videos payload.
 */
function normalizeVideosPayload(payload: VideosPayload | DiscoveryListPayload): VideosPayload & Partial<DiscoveryListPayload> {
  if ("items" in payload && Array.isArray(payload.items)) {
    return { ...payload, rows: payload.items };
  }
  return payload;
}

/**
 * Handle fetch similar/discovery videos payload through Client Discovery API v1.
 */
export async function fetchSimilarVideosPayload(query: SimilarQuery) {
  const url = buildSimilarUrl(query);
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = "Failed to load recommendations";
    try {
      const body = (await response.json()) as { error?: string };
      message = body?.error ?? message;
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(message);
  }
  return normalizeVideosPayload((await response.json()) as VideosPayload | DiscoveryListPayload);
}
