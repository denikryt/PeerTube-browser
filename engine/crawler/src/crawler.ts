/**
 * Module `engine/crawler/src/crawler.ts`: provide runtime functionality.
 */

import { setTimeout as sleep } from "node:timers/promises";
import { CrawlerStore } from "./db/instances.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
import { shouldTryAlternateProtocol } from "./error-classification.js";
import { createRequestLimiter, type RequestLimiter } from "./request-limiter.js";
import {
  loadHostsFromFile,
  normalizeHostToken,
  scopeHosts
} from "./host-filters.js";
import { fetchInstanceRegistryHosts } from "./instance-registry.js";
import type { CrawlOptions, Page, ServerFollowItem } from "./types.js";

const PAGE_SIZE = 50;

/**
 * Handle crawl.
 */
export async function crawl(options: CrawlOptions) {
  const store = new CrawlerStore({
    dbPath: options.dbPath,
    resume: options.resume,
    collectGraph: options.collectGraph,
    expandBeyondWhitelist: options.expandBeyondWhitelist
  });
  const whitelistUrl = ensureUrl(options.whitelistUrl);
  const fetchedWhitelistHosts = options.whitelistFile
    ? Array.from(loadHostsFromFile(options.whitelistFile))
    : await fetchInstanceRegistryHosts(whitelistUrl, {
        timeoutMs: options.timeoutMs,
        maxRetries: options.maxRetries
      });
  const includedHosts = loadHostsFromFile(options.hostsFile);
  const excludedHosts = loadHostsFromFile(options.excludeHostsFile);
  const filteredWhitelistHosts = scopeHosts(
    fetchedWhitelistHosts,
    includedHosts,
    excludedHosts
  );
  const whitelistHosts =
    options.maxInstances > 0
      ? filteredWhitelistHosts.slice(0, options.maxInstances)
      : filteredWhitelistHosts;
  if (whitelistHosts.length === 0) {
    throw new Error("Whitelist is empty after host include/exclude filtering.");
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
  console.log(
    `[crawl] whitelist=${whitelistHosts.length} expand=${options.expandBeyondWhitelist} graph=${options.collectGraph} concurrency=${options.concurrency} resume=${options.resume}`
  );

  if (!options.collectGraph && !options.expandBeyondWhitelist) {
    store.setState("finished_at", new Date().toISOString());
    console.log("[crawl] finished (no graph/expand work)");
    store.close();
    return;
  }

  const workers = Array.from({ length: options.concurrency }, () =>
    workerLoop(store, options, whitelistSet, excludedHosts, preferredProtocol)
  );
  await Promise.all(workers);

  store.setState("finished_at", new Date().toISOString());
  console.log("[crawl] finished");
  store.close();
}

/**
 * Handle worker loop.
 */
async function workerLoop(
  store: CrawlerStore,
  options: CrawlOptions,
  whitelistHosts: Set<string>,
  excludedHosts: Set<string>,
  preferredProtocol: string
) {
  while (true) {
    const host = store.claimNextHost();
    if (!host) {
      const nextDue = store.nextQueueTime();
      if (!nextDue) return;
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
      await processHost(
        host,
        store,
        options,
        whitelistHosts,
        excludedHosts,
        preferredProtocol
      );
      store.markDone(host);
      console.log(`[crawl] done ${host}`);
    } catch (error) {
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

/**
 * Handle process host.
 */
async function processHost(
  host: string,
  store: CrawlerStore,
  options: CrawlOptions,
  whitelistHosts: Set<string>,
  excludedHosts: Set<string>,
  preferredProtocol: string
) {
  // Nothing to do unless we are collecting edges or expanding discovery.
  if (!options.collectGraph && !options.expandBeyondWhitelist) return;
  const requestLimiter = createRequestLimiter(1, options.hostDelayMs);

  const following = await fetchAll(host, "following", options, preferredProtocol, requestLimiter);
  console.log(`[crawl] ${host} following=${following.length}`);
  for (const item of following) {
    const targetHost = extractFollowingHost(item, host);
    if (!targetHost) continue;
    if (excludedHosts.has(targetHost)) continue;
    if (options.expandBeyondWhitelist || whitelistHosts.has(targetHost)) {
      store.ensureInstance(targetHost);
      store.enqueueHost(targetHost);
    }
    if (options.collectGraph) {
      store.insertEdge(host, targetHost);
    }
  }

  const followers = await fetchAll(host, "followers", options, preferredProtocol, requestLimiter);
  console.log(`[crawl] ${host} followers=${followers.length}`);
  for (const item of followers) {
    const followerHost = extractFollowerHost(item, host);
    if (!followerHost) continue;
    if (excludedHosts.has(followerHost)) continue;
    if (options.expandBeyondWhitelist || whitelistHosts.has(followerHost)) {
      store.ensureInstance(followerHost);
      store.enqueueHost(followerHost);
    }
    if (options.collectGraph) {
      store.insertEdge(followerHost, host);
    }
  }
}

/**
 * Handle fetch all.
 */
async function fetchAll(
  host: string,
  kind: "following" | "followers",
  options: CrawlOptions,
  preferredProtocol: string,
  requestLimiter: RequestLimiter
) {
  const results: ServerFollowItem[] = [];
  let start = 0;

  while (true) {
    const page = await fetchPage(host, kind, start, options, preferredProtocol, requestLimiter);
    const data = Array.isArray(page.data) ? page.data : [];
    results.push(...data);

    if (page.total !== undefined) {
      if (start + PAGE_SIZE >= page.total) break;
    } else if (data.length < PAGE_SIZE) {
      break;
    }

    start += PAGE_SIZE;
  }

  return results;
}

/**
 * Handle fetch page.
 */
async function fetchPage(
  host: string,
  kind: string,
  start: number,
  options: CrawlOptions,
  preferredProtocol: string,
  requestLimiter: RequestLimiter
) {
  const primaryUrl = buildUrl(host, kind, start, PAGE_SIZE, preferredProtocol);

  try {
    return await requestLimiter.run(() => fetchJsonWithRetry<Page<ServerFollowItem>>(primaryUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries
    }));
  } catch (error) {
    if (!shouldTryAlternateProtocol(error)) throw error;
    const alternateProtocol = preferredProtocol === "https:" ? "http:" : "https:";
    const alternateUrl = buildUrl(host, kind, start, PAGE_SIZE, alternateProtocol);
    return await requestLimiter.run(() => fetchJsonWithRetry<Page<ServerFollowItem>>(alternateUrl, {
      timeoutMs: options.timeoutMs,
      maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
    }));
  }
}

/**
 * Handle build url.
 */
function buildUrl(host: string, kind: string, start: number, count: number, protocol: string) {
  const base = `${protocol}//${host}`;
  return `${base}/api/v1/server/${kind}?start=${start}&count=${count}`;
}

/**
 * Handle ensure url.
 */
function ensureUrl(input: string) {
  if (input.startsWith("http://") || input.startsWith("https://")) {
    return input;
  }
  return `https://${input}`;
}

/**
 * Handle extract following host.
 */
function extractFollowingHost(item: ServerFollowItem, currentHost: string): string | null {
  return extractHostFromRef(item.following, currentHost);
}

/**
 * Handle extract follower host.
 */
function extractFollowerHost(item: ServerFollowItem, currentHost: string): string | null {
  return extractHostFromRef(item.follower, currentHost);
}

/**
 * Handle extract host from ref.
 */
function extractHostFromRef(ref: ServerFollowItem["following"], currentHost: string): string | null {
  if (!ref) return null;
  const host = parseHost(ref);
  if (!host) return null;
  if (host === currentHost) return null;
  return host;
}

/**
 * Handle parse host.
 */
function parseHost(ref: ServerFollowItem["following"]): string | null {
  if (!ref) return null;
  if (typeof ref === "string") {
    return parseHostString(ref);
  }
  if (typeof ref === "object") {
    if (ref.host) return ref.host.toLowerCase();
    if (ref.hostname) return ref.hostname.toLowerCase();
    if (ref.url) return parseHostString(ref.url);
    if (ref.id) return parseHostString(ref.id);
    if (ref.name) return parseHostString(ref.name);
  }
  return null;
}

/**
 * Handle parse host string.
 */
function parseHostString(value: string): string | null {
  return normalizeHostToken(value);
}
