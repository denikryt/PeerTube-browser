const DEFAULT_API_BASE = window.location.origin;

function normalizeApiBase(value?: string | null): string | null {
  const base = (value ?? "").trim();
  return base.startsWith("http") ? base : null;
}

export function resolveApiBase(value?: string | null): string {
  const direct = normalizeApiBase(value);
  if (direct) {
    return direct;
  }
  const envBase = normalizeApiBase(import.meta.env.VITE_API_BASE);
  if (envBase) {
    return envBase;
  }
  return DEFAULT_API_BASE;
}
