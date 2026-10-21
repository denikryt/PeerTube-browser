/** Public Client Discovery v1 data access for Home. */
import { resolveClientApiBase } from "./api-base";
import type { DiscoveryListPayload } from "../types/videos";
import type { VideoFilters } from "../types/video-filters";
import type { HomeMode } from "../state/video-filters";

export interface DiscoveryFetchOptions {
  limit: number;
  cursor?: string | null;
  filters?: VideoFilters;
  apiBase?: string | null;
}

/** Error preserving the Client protocol code needed for stale-cursor recovery. */
export class DiscoveryApiError extends Error {
  readonly code: string | null;
  readonly status: number;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "DiscoveryApiError";
    this.status = status;
    this.code = code;
  }
}

/** Build one browser-facing Discovery URL; Engine internal routes never cross this boundary. */
export function buildDiscoveryUrl(source: HomeMode, options: DiscoveryFetchOptions): string {
  const url = new URL(`/api/v1/discovery/${source}`, resolveClientApiBase(options.apiBase));
  url.searchParams.set("limit", String(options.limit));
  if (options.cursor) url.searchParams.set("cursor", options.cursor);
  const filters = options.filters;
  if (filters) {
    if (filters.language) url.searchParams.set("language", filters.language);
    if (filters.category) url.searchParams.set("category", filters.category);
    if (filters.tag) url.searchParams.set("tag", filters.tag);
    if (filters.instance) url.searchParams.set("instance", filters.instance);
  }
  return url.toString();
}

/** Fetch one Discovery page from the Client backend and preserve structured errors. */
export async function fetchDiscoveryPayload(source: HomeMode, options: DiscoveryFetchOptions): Promise<DiscoveryListPayload> {
  const response = await fetch(buildDiscoveryUrl(source, options), { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    let code: string | null = null;
    try {
      const body = (await response.json()) as { error?: string; code?: string };
      message = body.error ?? message;
      code = typeof body.code === "string" ? body.code : null;
    } catch {
      // Keep the transport status if the Client returned a non-JSON failure.
    }
    throw new DiscoveryApiError(message, response.status, code);
  }
  return (await response.json()) as DiscoveryListPayload;
}
