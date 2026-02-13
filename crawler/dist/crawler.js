import { setTimeout as sleep } from "node:timers/promises";
import { CrawlerStore } from "./db.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { filterHosts, loadHostsFromFile, normalizeHostToken } from "./host-filters.js";
const PAGE_SIZE = 50;
export async function crawl(options) {
    const store = new CrawlerStore({
        dbPath: options.dbPath,
        resume: options.resume,
        collectGraph: options.collectGraph,
        expandBeyondWhitelist: options.expandBeyondWhitelist
    });
    const whitelistUrl = ensureUrl(options.whitelistUrl);
    const fetchedWhitelistHosts = options.whitelistFile
        ? Array.from(loadHostsFromFile(options.whitelistFile))
        : await fetchWhitelistHosts(whitelistUrl, options);
    const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
    const filteredWhitelistHosts = filterHosts(fetchedWhitelistHosts, excludedHosts);
    const whitelistHosts = options.maxInstances > 0
        ? filteredWhitelistHosts.slice(0, options.maxInstances)
        : filteredWhitelistHosts;
    if (whitelistHosts.length === 0) {
        throw new Error("Whitelist is empty after exclude-host filtering.");
    }
    const whitelistSet = new Set(whitelistHosts);
    const preferredProtocol = new URL(whitelistUrl).protocol;
    if (options.resume && (options.collectGraph || options.expandBeyondWhitelist)) {
        store.recoverQueue(options.expandBeyondWhitelist ? undefined : whitelistSet);
    }
    for (const host of whitelistHosts) {
        store.ensureInstance(host);
        if (options.collectGraph || options.expandBeyondWhitelist) {
            store.enqueueHost(host);
        }
    }
    store.setState("whitelist_url", whitelistUrl);
    store.setState("whitelist_count", String(whitelistHosts.length));
    store.setState("started_at", new Date().toISOString());
    console.log(`[crawl] whitelist=${whitelistHosts.length} expand=${options.expandBeyondWhitelist} graph=${options.collectGraph} concurrency=${options.concurrency} resume=${options.resume}`);
    if (!options.collectGraph && !options.expandBeyondWhitelist) {
        store.setState("finished_at", new Date().toISOString());
        console.log("[crawl] finished (no graph/expand work)");
        store.close();
        return;
    }
    const workers = Array.from({ length: options.concurrency }, () => workerLoop(store, options, whitelistSet, excludedHosts, preferredProtocol));
    await Promise.all(workers);
    store.setState("finished_at", new Date().toISOString());
    console.log("[crawl] finished");
    store.close();
}
async function workerLoop(store, options, whitelistHosts, excludedHosts, preferredProtocol) {
    while (true) {
        const host = store.claimNextHost();
        if (!host) {
            const nextDue = store.nextQueueTime();
            if (!nextDue)
                return;
            const delay = Math.max(100, nextDue - Date.now());
            await sleep(delay);
            continue;
        }
        try {
            if (excludedHosts.has(host)) {
                store.markDone(host);
                continue;
            }
            console.log(`[crawl] processing ${host}`);
            await processHost(host, store, options, whitelistHosts, excludedHosts, preferredProtocol);
            store.markDone(host);
            console.log(`[crawl] done ${host}`);
        }
        catch (error) {
            if (isNoNetworkError(error)) {
                throw error;
            }
            const message = error instanceof Error ? error.message : String(error);
            store.markError(host, message);
            console.warn(`[crawl] error ${host}: ${message}`);
            const errors = store.getErrorCount(host);
            if (errors < options.maxErrors) {
                const delay = Math.min(errors * 5000, 30000);
                store.enqueueHost(host, delay);
            }
        }
    }
}
async function processHost(host, store, options, whitelistHosts, excludedHosts, preferredProtocol) {
    // Nothing to do unless we are collecting edges or expanding discovery.
    if (!options.collectGraph && !options.expandBeyondWhitelist)
        return;
    const following = await fetchAll(host, "following", options, preferredProtocol);
    console.log(`[crawl] ${host} following=${following.length}`);
    for (const item of following) {
        const targetHost = extractFollowingHost(item, host);
        if (!targetHost)
            continue;
        if (excludedHosts.has(targetHost))
            continue;
        if (options.expandBeyondWhitelist || whitelistHosts.has(targetHost)) {
            store.ensureInstance(targetHost);
            store.enqueueHost(targetHost);
        }
        if (options.collectGraph) {
            store.insertEdge(host, targetHost);
        }
    }
    const followers = await fetchAll(host, "followers", options, preferredProtocol);
    console.log(`[crawl] ${host} followers=${followers.length}`);
    for (const item of followers) {
        const followerHost = extractFollowerHost(item, host);
        if (!followerHost)
            continue;
        if (excludedHosts.has(followerHost))
            continue;
        if (options.expandBeyondWhitelist || whitelistHosts.has(followerHost)) {
            store.ensureInstance(followerHost);
            store.enqueueHost(followerHost);
        }
        if (options.collectGraph) {
            store.insertEdge(followerHost, host);
        }
    }
}
async function fetchAll(host, kind, options, preferredProtocol) {
    const results = [];
    let start = 0;
    while (true) {
        const page = await fetchPage(host, kind, start, options, preferredProtocol);
        const data = Array.isArray(page.data) ? page.data : [];
        results.push(...data);
        if (page.total !== undefined) {
            if (start + PAGE_SIZE >= page.total)
                break;
        }
        else if (data.length < PAGE_SIZE) {
            break;
        }
        start += PAGE_SIZE;
    }
    return results;
}
async function fetchPage(host, kind, start, options, preferredProtocol) {
    const primaryUrl = buildUrl(host, kind, start, PAGE_SIZE, preferredProtocol);
    try {
        return await fetchJsonWithRetry(primaryUrl, {
            timeoutMs: options.timeoutMs,
            maxRetries: options.maxRetries
        });
    }
    catch {
        const alternateProtocol = preferredProtocol === "https:" ? "http:" : "https:";
        const alternateUrl = buildUrl(host, kind, start, PAGE_SIZE, alternateProtocol);
        return await fetchJsonWithRetry(alternateUrl, {
            timeoutMs: options.timeoutMs,
            maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
        });
    }
}
function buildUrl(host, kind, start, count, protocol) {
    const base = `${protocol}//${host}`;
    return `${base}/api/v1/server/${kind}?start=${start}&count=${count}`;
}
function ensureUrl(input) {
    if (input.startsWith("http://") || input.startsWith("https://")) {
        return input;
    }
    return `https://${input}`;
}
async function fetchWhitelistHosts(url, options) {
    const payload = await fetchJsonWithRetry(url, {
        timeoutMs: options.timeoutMs,
        maxRetries: options.maxRetries
    });
    const entries = extractWhitelistEntries(payload);
    const hosts = new Set();
    for (const entry of entries) {
        const hostValue = extractWhitelistHost(entry);
        if (!hostValue)
            continue;
        const normalized = parseHostString(hostValue);
        if (normalized) {
            hosts.add(normalized);
        }
    }
    if (hosts.size === 0) {
        throw new Error("Whitelist contained no hosts.");
    }
    return Array.from(hosts);
}
function extractWhitelistEntries(payload) {
    if (Array.isArray(payload)) {
        return payload;
    }
    if (payload && typeof payload === "object") {
        const data = payload.data;
        if (Array.isArray(data)) {
            return data;
        }
    }
    throw new Error("Unexpected whitelist JSON shape.");
}
function extractWhitelistHost(entry) {
    if (!entry)
        return null;
    if (typeof entry === "string" || typeof entry === "number") {
        const value = String(entry).trim();
        return value.length > 0 ? value : null;
    }
    if (typeof entry === "object") {
        const host = entry.host;
        if (typeof host === "string" || typeof host === "number") {
            const value = String(host).trim();
            return value.length > 0 ? value : null;
        }
    }
    return null;
}
function extractFollowingHost(item, currentHost) {
    return extractHostFromRef(item.following, currentHost);
}
function extractFollowerHost(item, currentHost) {
    return extractHostFromRef(item.follower, currentHost);
}
function extractHostFromRef(ref, currentHost) {
    if (!ref)
        return null;
    const host = parseHost(ref);
    if (!host)
        return null;
    if (host === currentHost)
        return null;
    return host;
}
function parseHost(ref) {
    if (!ref)
        return null;
    if (typeof ref === "string") {
        return parseHostString(ref);
    }
    if (typeof ref === "object") {
        if (ref.host)
            return ref.host.toLowerCase();
        if (ref.hostname)
            return ref.hostname.toLowerCase();
        if (ref.url)
            return parseHostString(ref.url);
        if (ref.id)
            return parseHostString(ref.id);
        if (ref.name)
            return parseHostString(ref.name);
    }
    return null;
}
function parseHostString(value) {
    return normalizeHostToken(value);
}
