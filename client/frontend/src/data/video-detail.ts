/**
 * Client-backed video detail data helpers.
 *
 * The Vue detail page resolves metadata only through the Client backend. Direct
 * PeerTube instance probing from the old page is intentionally removed so the
 * frontend boundary stays narrow and testable.
 */

import { resolveClientApiBase } from "./api-base";

export interface VideoMetadata {
  videoUuid?: string;
  title?: string;
  channelName?: string;
  channelUrl?: string;
  channelAvatarUrl?: string;
  subscribersCount?: number | null;
  instanceName?: string;
  instanceUrl?: string;
  instanceAvatarUrl?: string;
  accountName?: string;
  accountUrl?: string;
  accountAvatarUrl?: string;
  embedUrl?: string;
  originalUrl?: string;
  views?: number | null;
  likes?: number | null;
  dislikes?: number | null;
  description?: string;
  publishedAt?: number | null;
}

/** Fetch one video metadata row by host-scoped identity. */
export async function fetchVideoMetadataPayload(options: {
  id: string;
  host: string;
  apiBase?: string | null;
}): Promise<VideoMetadata> {
  const url = new URL(`/api/v1/videos/${encodeURIComponent(options.id)}`, resolveClientApiBase(options.apiBase));
  url.searchParams.set("host", options.host);
  const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = "Failed to load video";
    try {
      const payload = (await response.json()) as { error?: string };
      message = payload.error ?? message;
    } catch {
      // Keep the generic user-facing message when the response is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as VideoMetadata;
}
