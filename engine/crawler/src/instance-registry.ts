/**
 * JoinPeerTube instance-registry access shared by production crawling and live smoke coverage.
 *
 * The parser deliberately preserves registry order while removing duplicate or malformed
 * host tokens so live diagnostics remain reproducible and production discovery behavior
 * does not diverge from the smoke runner.
 */

import { fetchJsonWithRetry } from "./http.js";
import { normalizeHostToken } from "./host-filters.js";

export const DEFAULT_JOINPEERTUBE_WHITELIST_URL =
  "https://instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true";

export interface InstanceRegistryFetchOptions {
  timeoutMs: number;
  maxRetries: number;
}

/** Extract normalized hosts from supported JoinPeerTube list/object payloads. */
export function parseInstanceRegistryHosts(payload: unknown): string[] {
  const entries = extractRegistryEntries(payload);
  const seen = new Set<string>();
  const hosts: string[] = [];

  for (const entry of entries) {
    const raw = extractRegistryHost(entry);
    if (!raw) continue;
    const normalized = normalizeHostToken(raw);
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    hosts.push(normalized);
  }

  if (hosts.length === 0) {
    throw new Error("Whitelist contained no hosts.");
  }
  return hosts;
}

/** Fetch and parse registry hosts through the crawler's standard retry boundary. */
export async function fetchInstanceRegistryHosts(
  url: string,
  options: InstanceRegistryFetchOptions
): Promise<string[]> {
  const payload = await fetchJsonWithRetry<unknown>(url, options);
  return parseInstanceRegistryHosts(payload);
}

/** Accept the two registry envelope shapes already supported by the crawler. */
function extractRegistryEntries(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const data = (payload as { data?: unknown }).data;
    if (Array.isArray(data)) return data;
  }
  throw new Error("Unexpected whitelist JSON shape.");
}

/** Extract one host token while ignoring unrelated registry metadata. */
function extractRegistryHost(entry: unknown): string | null {
  if (!entry) return null;
  if (typeof entry === "string" || typeof entry === "number") {
    const value = String(entry).trim();
    return value || null;
  }
  if (typeof entry === "object") {
    const host = (entry as { host?: unknown }).host;
    if (typeof host === "string" || typeof host === "number") {
      const value = String(host).trim();
      return value || null;
    }
  }
  return null;
}
