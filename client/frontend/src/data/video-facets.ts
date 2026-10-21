/** Public global video-facet data access shared by Home and Search controls. */
import { resolveClientApiBase } from "./api-base";
import type { VideoFacetsPayload } from "../types/video-filters";

/** Build the public Client facets URL; the browser never calls Engine internals. */
export function buildVideoFacetsUrl(apiBase?: string | null): string {
  return new URL("/api/v1/video-facets", resolveClientApiBase(apiBase)).toString();
}

/** Fetch global service-visible facets independently from feed/search result loading. */
export async function fetchVideoFacetsPayload(apiBase?: string | null): Promise<VideoFacetsPayload> {
  const response = await fetch(buildVideoFacetsUrl(apiBase), { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { error?: string };
      message = body.error ?? message;
    } catch {
      // Preserve the HTTP status when the failure body is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as VideoFacetsPayload;
}
