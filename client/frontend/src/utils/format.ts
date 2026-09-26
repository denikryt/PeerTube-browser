/**
 * Shared frontend formatting helpers that preserve the current vanilla pages' output.
 */

/** Escape text before embedding it into current string-based HTML renderers. */
export function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "\"":
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return char;
    }
  });
}

/** Format a video duration with the existing feed/video-page fallback of `0:00`. */
export function formatDuration(value: number | null) {
  if (!value || !Number.isFinite(value)) return "0:00";
  const total = Math.max(0, Math.round(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** Format relative time with the current coarse page-level thresholds. */
export function formatTimeAgo(timestampMs: number, nowMs = Date.now()) {
  const diffMs = Math.max(0, nowMs - timestampMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const month = 30 * day;
  const year = 365 * day;

  if (diffMs < minute) return "just now";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)} minutes ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)} hours ago`;
  if (diffMs < month) return `${Math.floor(diffMs / day)} days ago`;
  if (diffMs < year) return `${Math.floor(diffMs / month)} months ago`;
  return `${Math.floor(diffMs / year)} years ago`;
}

/** Normalize numeric API fields without changing the current permissive string handling. */
export function normalizeStatValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

/** Format stat values with the current `--` missing-value fallback. */
export function formatStatValue(value: number | null | undefined, formatter = new Intl.NumberFormat("en-US")) {
  if (value == null || !Number.isFinite(value)) return "--";
  return formatter.format(value);
}

/** Format recommendation debug floats without changing the current diagnostic text. */
export function formatDebugNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return Number(value).toFixed(3);
}

/** Format recommendation debug ranks with the current integer truncation. */
export function formatDebugInt(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return String(Math.trunc(value));
}
