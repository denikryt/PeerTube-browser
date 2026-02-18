/**
 * Module `client/frontend/src/data/api-base.ts`: provide runtime functionality.
 */

const DEFAULT_CLIENT_API_BASE = window.location.origin;

/**
 * Handle normalize api base.
 */
function normalizeApiBase(value?: string | null): string | null {
  const base = (value ?? "").trim();
  return base.startsWith("http") ? base : null;
}

/**
 * Handle resolve client api base.
 */
export function resolveClientApiBase(value?: string | null): string {
  const envBase = normalizeApiBase(import.meta.env.VITE_CLIENT_API_BASE);
  if (envBase) {
    return envBase;
  }
  const direct = normalizeApiBase(value);
  if (direct) {
    return direct;
  }
  return DEFAULT_CLIENT_API_BASE;
}
