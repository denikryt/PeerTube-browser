/**
 * Small query-state helpers for vanilla page controllers.
 */

/** Return a fresh URLSearchParams instance for the provided location search. */
export function readSearchParams(search = window.location.search) {
  return new URLSearchParams(search);
}
