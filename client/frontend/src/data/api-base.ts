const DEFAULT_ENGINE_API_BASE = window.location.origin;
const DEFAULT_CLIENT_API_BASE = window.location.origin;

function normalizeApiBase(value?: string | null): string | null {
  const base = (value ?? "").trim();
  return base.startsWith("http") ? base : null;
}

export function resolveEngineApiBase(value?: string | null): string {
  const direct = normalizeApiBase(value);
  if (direct) {
    return direct;
  }
  const envBase = normalizeApiBase(import.meta.env.VITE_ENGINE_API_BASE);
  if (envBase) {
    return envBase;
  }
  return DEFAULT_ENGINE_API_BASE;
}

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
