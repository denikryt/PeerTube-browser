/** Pure URL-state helpers shared by Home and video Search filters. */
import type { VideoFilters } from "../types/video-filters";

export type HomeMode = "recommendations" | "fresh" | "popular" | "random";

const FILTER_KEYS = ["language", "category", "tag", "instance"] as const;
const HOME_MODES = new Set<HomeMode>(["recommendations", "fresh", "popular", "random"]);

/** Return an independent empty selection object for callers that will mutate controls. */
export function emptyVideoFilters(): VideoFilters {
  return { language: null, category: null, tag: null, instance: null };
}

/** Normalize a Vue Router query value without assigning semantic meaning to it. */
function queryValue(value: unknown): string | null {
  if (Array.isArray(value)) value = value[0];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed || null;
}

/** Parse the four supported filter values from route query state. */
export function parseVideoFilterQuery(query: Record<string, unknown>): VideoFilters {
  return {
    language: queryValue(query.language),
    category: queryValue(query.category),
    tag: queryValue(query.tag),
    instance: queryValue(query.instance)
  };
}

/** Serialize controls to a compact route query, omitting blank values. */
export function serializeVideoFilters(filters: Partial<VideoFilters>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const key of FILTER_KEYS) {
    const value = queryValue(filters[key]);
    if (value) result[key] = value;
  }
  return result;
}

/** Resolve the canonical Home mode; unknown external values fall back to Recommended. */
export function parseHomeMode(value: unknown): HomeMode {
  const normalized = queryValue(value) as HomeMode | null;
  return normalized && HOME_MODES.has(normalized) ? normalized : "recommendations";
}

/** Serialize Home mode while keeping the default mode out of clean URLs. */
export function serializeHomeMode(mode: HomeMode): Record<string, string> {
  return mode === "recommendations" ? {} : { mode };
}

/** Stable Home selection identity including mode and all filter dimensions. */
export function homeSelectionKey(mode: HomeMode, filters: VideoFilters): string {
  return JSON.stringify([mode, ...FILTER_KEYS.map((key) => filters[key])]);
}

/** Stable Search video selection identity including query and filters. */
export function searchSelectionKey(query: string, filters: VideoFilters): string {
  return JSON.stringify([query.trim(), ...FILTER_KEYS.map((key) => filters[key])]);
}
