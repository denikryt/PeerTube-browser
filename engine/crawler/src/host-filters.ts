/**
 * Module `engine/crawler/src/host-filters.ts`: provide runtime functionality.
 */

import fs from "node:fs";

/**
 * Handle load hosts from file.
 */
export function loadHostsFromFile(filePath: string | null | undefined): Set<string> {
  const hosts = new Set<string>();
  if (!filePath) return hosts;

  const raw = fs.readFileSync(filePath, "utf8");
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const host = normalizeHostToken(trimmed);
    if (host) hosts.add(host);
  }
  return hosts;
}

/** Read an optional include constraint; an explicit empty file selects no hosts. */
export function loadIncludedHostsFromFile(filePath: string | null | undefined): Set<string> | null {
  return filePath ? loadHostsFromFile(filePath) : null;
}

/**
 * Handle apply include hosts filter.
 */
export function includeHosts(hosts: string[], included: Set<string> | null): string[] {
  if (included === null) return hosts;
  return hosts.filter((host) => included.has(host.toLowerCase()));
}

/**
 * Handle filter hosts.
 */
export function filterHosts(hosts: string[], excluded: Set<string>): string[] {
  if (excluded.size === 0) return hosts;
  return hosts.filter((host) => !excluded.has(host.toLowerCase()));
}

/**
 * Handle apply include and exclude host scoping together.
 */
export function scopeHosts(
  hosts: string[],
  included: Set<string> | null,
  excluded: Set<string>,
  selected?: readonly string[]
): string[] {
  // An internal host restriction can only narrow an operator include file.
  const selectedHosts = selected === undefined ? null : new Set(selected.map(host => host.toLowerCase()));
  return filterHosts(includeHosts(includeHosts(hosts, included), selectedHosts), excluded);
}

/**
 * Handle normalize host token.
 */
export function normalizeHostToken(value: string): string | null {
  const raw = value.trim().toLowerCase();
  if (!raw) return null;

  try {
    if (raw.startsWith("http://") || raw.startsWith("https://")) {
      const host = new URL(raw).hostname.toLowerCase();
      return host || null;
    }
    if (raw.includes("/")) {
      const host = new URL(`https://${raw}`).hostname.toLowerCase();
      return host || null;
    }
    return raw.replace(/^\.+|\.+$/g, "") || null;
  } catch {
    return null;
  }
}
