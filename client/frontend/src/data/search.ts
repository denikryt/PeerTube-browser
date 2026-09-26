/**
 * Client Search API v1 data helpers.
 *
 * Video filters are sent only to the public Client video-search route. Channel
 * search intentionally remains query-only so video metadata controls do not
 * cross the channel-search contract.
 */

import type { ChannelSearchPayload, VideoSearchPayload } from "../types/search";
import type { VideoFilters } from "../types/video-filters";
import { resolveClientApiBase } from "./api-base";

export interface SearchFetchOptions {
  q: string;
  limit?: number;
  cursor?: string | null;
  filters?: VideoFilters;
  apiBase?: string | null;
}

function buildSearchUrl(path: string, options: SearchFetchOptions, includeVideoFilters: boolean) {
  const url = new URL(path, resolveClientApiBase(options.apiBase));
  url.searchParams.set("q", options.q.trim());
  if (options.limit && options.limit > 0) url.searchParams.set("limit", String(options.limit));
  if (options.cursor) url.searchParams.set("cursor", options.cursor);
  if (includeVideoFilters && options.filters) {
    const { language, category, tag, instance } = options.filters;
    if (language) url.searchParams.set("language", language);
    if (category) url.searchParams.set("category", category);
    if (tag) url.searchParams.set("tag", tag);
    if (instance) url.searchParams.set("instance", instance);
  }
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
  return fetchSearchJson<VideoSearchPayload>(buildSearchUrl("/api/v1/search/videos", options, true));
}

/** Fetch public v1 channel search results without video filters. */
export function fetchChannelSearchPayload(options: SearchFetchOptions) {
  return fetchSearchJson<ChannelSearchPayload>(buildSearchUrl("/api/v1/search/channels", options, false));
}

/** Build public Client video-search URL for boundary/state tests. */
export function buildVideoSearchUrl(options: SearchFetchOptions) {
  return buildSearchUrl("/api/v1/search/videos", options, true);
}

/** Build public Client channel-search URL for boundary/state tests. */
export function buildChannelSearchUrl(options: SearchFetchOptions) {
  return buildSearchUrl("/api/v1/search/channels", options, false);
}
