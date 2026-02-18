/**
 * Module `client/frontend/src/data/videos.ts`: provide runtime functionality.
 */

import type { VideoRow, VideosPayload } from "../types/videos";
import { fetchJsonWithCache } from "./cache";
import { getRandomLikes } from "./local-likes";
import { resolveClientApiBase } from "./api-base";

export interface SimilarQuery {
  id?: string | null;
  host?: string | null;
  limit?: string | null;
  apiBase?: string | null;
  random?: string | null;
  debug?: string | null;
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
    debug: params.get("debug")
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
  const url = new URL("/recommendations", apiBase);
  if (query.id) url.searchParams.set("id", query.id);
  if (query.host) url.searchParams.set("host", query.host);
  if (query.limit) url.searchParams.set("limit", query.limit);
  if (query.random) url.searchParams.set("random", query.random);
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
export async function fetchSimilarVideosPayload(query: SimilarQuery) {
  const url = buildSimilarUrl(query);
  const likes = getRandomLikes();
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({ likes })
  });
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
  return (await response.json()) as VideosPayload;
}
