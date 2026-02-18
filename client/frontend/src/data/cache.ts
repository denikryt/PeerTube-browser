/**
 * Module `client/frontend/src/data/cache.ts`: provide runtime functionality.
 */

interface CacheEntry<T> {
  expiresAt: number;
  payload: T;
}

interface CacheOptions {
  cacheKey?: string;
  ttlMs?: number;
}

const DEFAULT_TTL_MS = 2 * 60 * 1000;

export async function fetchJsonWithCache<T>(
  url: string,
  options: CacheOptions = {}
): Promise<T> {
  const cacheKey = options.cacheKey ?? url;
  const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;

  if (ttlMs > 0) {
    const cached = readCache<T>(cacheKey);
    if (cached !== null) {
      return cached;
    }
  }

  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }
  const payload = (await response.json()) as T;

  if (ttlMs > 0) {
    writeCache(cacheKey, payload, ttlMs);
  }

  return payload;
}

function readCache<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEntry<T>;
    if (!parsed || typeof parsed.expiresAt !== "number") return null;
    if (Date.now() > parsed.expiresAt) {
      sessionStorage.removeItem(key);
      return null;
    }
    return parsed.payload ?? null;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, payload: T, ttlMs: number) {
  try {
    const entry: CacheEntry<T> = {
      expiresAt: Date.now() + ttlMs,
      payload
    };
    sessionStorage.setItem(key, JSON.stringify(entry));
  } catch {
    // Ignore storage failures (quota/private mode).
  }
}
