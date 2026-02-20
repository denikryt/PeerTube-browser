/**
 * Module `engine/crawler/src/host-filters.ts`: provide runtime functionality.
 */
import fs from "node:fs";
/**
 * Handle load hosts from file.
 */
export function loadHostsFromFile(filePath) {
    const hosts = new Set();
    if (!filePath)
        return hosts;
    const raw = fs.readFileSync(filePath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#"))
            continue;
        const host = normalizeHostToken(trimmed);
        if (host)
            hosts.add(host);
    }
    return hosts;
}
/**
 * Handle filter hosts.
 */
export function filterHosts(hosts, excluded) {
    if (excluded.size === 0)
        return hosts;
    return hosts.filter((host) => !excluded.has(host.toLowerCase()));
}
/**
 * Handle normalize host token.
 */
export function normalizeHostToken(value) {
    const raw = value.trim().toLowerCase();
    if (!raw)
        return null;
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
    }
    catch {
        return null;
    }
}
