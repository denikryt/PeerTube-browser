/**
 * Safe public ActivityPub enrichment for PeerTube live-video metadata.
 *
 * This module is intentionally narrow: it validates a known PeerTube Video
 * object URL before network access, rejects redirects, validates response
 * identity, and returns only the public live fields missing from REST.
 */

import { fetchJsonWithRetry } from "./http.js";

const ACTIVITYPUB_ACCEPT =
  'application/activity+json, application/ld+json; profile="https://www.w3.org/ns/activitystreams"';

export interface ActivityPubLiveMetadata {
  permanentLive: boolean | null;
  liveSaveReplay: boolean | null;
}

export interface ActivityPubFetchOptions {
  timeoutMs: number;
  maxRetries: number;
}

/**
 * Validate a remote-provided ActivityPub object URL before any outbound access.
 */
export function validateActivityPubCandidateUrl(
  candidate: string,
  expectedHost: string
): URL {
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    throw new Error("invalid ActivityPub video URL");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("ActivityPub video URL must use http or https");
  }
  if (url.username || url.password) {
    throw new Error("ActivityPub video URL must not contain credentials");
  }
  if (normalizeHost(url.host) !== normalizeHost(expectedHost)) {
    throw new Error("ActivityPub video URL host does not match crawled instance");
  }
  return url;
}

/**
 * Fetch and validate the public PeerTube ActivityPub Video object used only for
 * live-save/permanent-live parity enrichment.
 */
export async function fetchActivityPubLiveMetadata(
  candidate: string,
  expectedHost: string,
  expectedUuid: string | null,
  options: ActivityPubFetchOptions
): Promise<ActivityPubLiveMetadata> {
  const url = validateActivityPubCandidateUrl(candidate, expectedHost);
  const payload = await fetchJsonWithRetry<Record<string, unknown>>(url.toString(), {
    timeoutMs: options.timeoutMs,
    maxRetries: options.maxRetries,
    accept: ACTIVITYPUB_ACCEPT,
    redirect: "error"
  });

  if (payload.type !== "Video") {
    throw new Error("ActivityPub object is not a Video");
  }
  const returnedId = typeof payload.id === "string" ? payload.id : null;
  if (!returnedId || canonicalIdentityUrl(returnedId) !== canonicalIdentityUrl(url.toString())) {
    throw new Error("ActivityPub Video id does not match expected video URL");
  }
  if (
    expectedUuid &&
    typeof payload.uuid === "string" &&
    payload.uuid !== expectedUuid
  ) {
    throw new Error("ActivityPub Video uuid does not match expected video UUID");
  }

  return {
    permanentLive: toNullableBoolean(payload.permanentLive),
    liveSaveReplay: toNullableBoolean(payload.liveSaveReplay)
  };
}

/** Normalize host text while preserving development ports used by fixtures. */
function normalizeHost(value: string): string {
  const raw = value.trim().toLowerCase().replace(/^\.+|\.+$/g, "");
  if (raw.startsWith("http://") || raw.startsWith("https://")) {
    return new URL(raw).host.toLowerCase();
  }
  return raw;
}

/** Compare protocol object identities without a meaningless trailing slash. */
function canonicalIdentityUrl(value: string): string {
  const url = new URL(value);
  url.hash = "";
  const text = url.toString();
  return text.endsWith("/") ? text.slice(0, -1) : text;
}

/** Keep absent public live booleans distinct from explicit false. */
function toNullableBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}
