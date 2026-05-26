/**
 * Feed mode URL-state helpers that preserve the current `mode=random` query contract.
 */

export type FeedMode = "random" | "recommendations";

/** Resolve the current feed mode from the `mode` query parameter. */
export function resolveFeedMode(searchParams: URLSearchParams): FeedMode {
  const raw = searchParams.get("mode");
  return raw === "random" ? "random" : "recommendations";
}

/** Mutate browser location search with the current mode/id/uuid behavior. */
export function setFeedMode(mode: FeedMode, locationRef: Location = window.location) {
  const next = new URLSearchParams(locationRef.search);
  if (mode === "random") {
    next.set("mode", "random");
  } else {
    next.delete("mode");
  }
  next.delete("id");
  next.delete("uuid");
  locationRef.search = next.toString();
}
