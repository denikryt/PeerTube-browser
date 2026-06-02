/**
 * Client Search API v1 data helpers.
 *
 * These helpers intentionally resolve only the Client backend base URL and call
 * public `/api/v1/search/...` routes so frontend search never depends on Engine
 * internal provider routes or legacy channel endpoints.
 */

import type { ChannelSearchPayload, VideoSearchPayload } from "../types/search";
import { resolveClientApiBase } from "./api-base";

export interface SearchFetchOptions {
  q: string;
  limit?: number;
  cursor?: string | null;
  apiBase?: string | null;
}

function buildSearchUrl(path: string, options: SearchFetchOptions) {
  const url = new URL(path, resolveClientApiBase(options.apiBase));
  url.searchParams.set("q", options.q.trim());
  if (options.limit && options.limit > 0) url.searchParams.set("limit", String(options.limit));
  if (options.cursor) url.searchParams.set("cursor", options.cursor);
  return url.toString();
}

async function fetchSearchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { error?: string };
      message = payload.error ?? message;
    } catch {
      // Preserve the HTTP status message when the server did not return JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

/** Fetch public v1 video search results from the Client backend. */
export function fetchVideoSearchPayload(options: SearchFetchOptions) {
  return fetchSearchJson<VideoSearchPayload>(buildSearchUrl("/api/v1/search/videos", options));
}

/** Fetch public v1 channel search results from the Client backend. */
export function fetchChannelSearchPayload(options: SearchFetchOptions) {
  return fetchSearchJson<ChannelSearchPayload>(buildSearchUrl("/api/v1/search/channels", options));
}

/** Build public Client search URLs for boundary tests and UI state assertions. */
export function buildVideoSearchUrl(options: SearchFetchOptions) {
  return buildSearchUrl("/api/v1/search/videos", options);
}

/** Build public Client channel-search URLs for boundary tests and UI state assertions. */
export function buildChannelSearchUrl(options: SearchFetchOptions) {
  return buildSearchUrl("/api/v1/search/channels", options);
}
