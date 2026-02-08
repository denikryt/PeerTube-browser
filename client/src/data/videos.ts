import type { VideoRow, VideosPayload } from "../types/videos";
import { fetchJsonWithCache } from "./cache";
import { getRandomLikes } from "./local-likes";

export interface SimilarQuery {
  id?: string | null;
  host?: string | null;
  limit?: string | null;
  apiBase?: string | null;
  random?: string | null;
  debug?: string | null;
}

const STATIC_VIDEO_URLS = ["/videos.json", "./videos.json", "videos.json"];
const DEFAULT_API_BASE = window.location.origin;

export function parseSimilarQuery(params: URLSearchParams): SimilarQuery {
  return {
    id: params.get("similarId") ?? params.get("id") ?? params.get("video_id") ?? params.get("videoId"),
    host: params.get("host") ?? params.get("instance_domain") ?? params.get("instanceDomain"),
    limit: params.get("limit"),
    apiBase: params.get("api") ?? params.get("apiBase"),
    random: params.get("random"),
    debug: params.get("debug")
  };
}

export function resolveApiBase(query: SimilarQuery) {
  const base = query.apiBase ?? "";
  return base && base.startsWith("http") ? base : DEFAULT_API_BASE;
}

export function buildSimilarUrl(query: SimilarQuery) {
  const apiBase = resolveApiBase(query);
  const url = new URL("/api/similar", apiBase);
  if (query.id) url.searchParams.set("id", query.id);
  if (query.host) url.searchParams.set("host", query.host);
  if (query.limit) url.searchParams.set("limit", query.limit);
  if (query.random) url.searchParams.set("random", query.random);
  if (query.debug) url.searchParams.set("debug", query.debug);
  return url.toString();
}

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

export async function fetchSimilarVideosPayload(query: SimilarQuery) {
  const url = buildSimilarUrl(query);
  const likes = getRandomLikes();
  if (likes.length) {
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
  return fetchJsonWithCache<VideosPayload>(url, {
    cacheKey: `similar:${url}`,
    ttlMs: 0
  });
}
