import type { ChannelRow, ChannelsPayload } from "../types/channels";
import { fetchJsonWithCache } from "./cache";

const DEFAULT_API_BASE = window.location.origin;
const DEFAULT_CACHE_TTL_MS = 30 * 1000;

export function resolveApiBase(apiBase?: string | null) {
  const base = apiBase ?? "";
  return base && base.startsWith("http") ? base : DEFAULT_API_BASE;
}

type FetchChannelsOptions = {
  apiBase?: string | null;
  cacheTtlMs?: number;
  limit?: number;
  offset?: number;
  q?: string;
  instance?: string;
  minFollowers?: number;
  minVideos?: number;
  maxVideos?: number | null;
  sort?: "name" | "instance" | "videos" | "followers" | "checked";
  dir?: "asc" | "desc";
};

export async function fetchChannelsPayload(options: FetchChannelsOptions = {}) {
  const apiBase = resolveApiBase(options.apiBase);
  const url = new URL("/api/channels", apiBase);
  if (options.limit && options.limit > 0) url.searchParams.set("limit", String(options.limit));
  if (typeof options.offset === "number" && options.offset >= 0) {
    url.searchParams.set("offset", String(options.offset));
  }
  if (options.q?.trim()) url.searchParams.set("q", options.q.trim());
  if (options.instance?.trim()) url.searchParams.set("instance", options.instance.trim());
  if (typeof options.minFollowers === "number" && options.minFollowers > 0) {
    url.searchParams.set("minFollowers", String(Math.floor(options.minFollowers)));
  }
  if (typeof options.minVideos === "number" && options.minVideos > 0) {
    url.searchParams.set("minVideos", String(Math.floor(options.minVideos)));
  }
  if (typeof options.maxVideos === "number" && options.maxVideos >= 0) {
    url.searchParams.set("maxVideos", String(Math.floor(options.maxVideos)));
  }
  if (options.sort) url.searchParams.set("sort", options.sort);
  if (options.dir) url.searchParams.set("dir", options.dir);
  return fetchJsonWithCache<ChannelsPayload | ChannelRow[]>(url.toString(), {
    cacheKey: `channels:${url}`,
    ttlMs: options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS
  });
}
