import { Command } from "commander";
import { ChannelStore } from "./db.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
const program = new Command();
program
    .option("--db <path>", "SQLite DB path", "data/crawl.db")
    .option("--concurrency <number>", "Concurrent instances", "4")
    .option("--timeout <ms>", "HTTP timeout in ms", "5000")
    .option("--max-retries <number>", "HTTP retry attempts", "3")
    .option("--host <host>", "Check only a single instance host")
    .option("--errors-only", "Check only instances with health_status=error", false)
    .option("--min-age-days <number>", "Only check instances last health checked at least this many days ago")
    .option("--min-age-min <number>", "Only check instances last health checked at least this many minutes ago")
    .option("--min-age-sec <number>", "Only check instances last health checked at least this many seconds ago");
program.parse(process.argv);
const options = program.opts();
try {
    await checkInstancesHealth({
        dbPath: options.db,
        concurrency: Number(options.concurrency),
        timeoutMs: Number(options.timeout),
        maxRetries: Number(options.maxRetries),
        minAgeDays: parseOptionalNumber(options.minAgeDays),
        minAgeMin: parseOptionalNumber(options.minAgeMin),
        minAgeSec: parseOptionalNumber(options.minAgeSec),
        host: parseOptionalHost(options.host),
        errorsOnly: Boolean(options.errorsOnly)
    });
}
catch (error) {
    if (isNoNetworkError(error)) {
        console.error("[instances-health] no network detected; stopping without progress updates");
        process.exit(1);
    }
    throw error;
}
async function checkInstancesHealth(options) {
    const store = new ChannelStore({ dbPath: options.dbPath });
    const minAgeMs = computeMinAgeMs(options);
    const hosts = options.host
        ? [options.host]
        : options.errorsOnly
            ? store.listErrorInstancesNeedingHealth(minAgeMs)
            : store.listInstancesNeedingHealth(minAgeMs);
    const workerCount = Math.min(options.concurrency, Math.max(1, hosts.length));
    const total = hosts.length;
    let processed = 0;
    const ageLabel = formatMinAgeLabel(options);
    const errorsLabel = options.errorsOnly ? " errors_only=true" : "";
    console.log(`[instances-health] instances=${total} concurrency=${workerCount}${ageLabel}${errorsLabel}`);
    const queue = hosts.slice();
    const workers = Array.from({ length: workerCount }, () => workerLoop(queue, store, options, total, () => {
        processed += 1;
        return processed;
    }));
    await Promise.all(workers);
    console.log("[instances-health] finished");
    store.close();
}
async function workerLoop(queue, store, options, total, nextProcessed) {
    while (true) {
        const host = queue.pop();
        if (!host)
            return;
        await processInstance(host, store, options, total, nextProcessed);
    }
}
async function processInstance(host, store, options, total, nextProcessed) {
    const normalizedHost = host.toLowerCase();
    const current = nextProcessed();
    console.log(`[instances-health] start ${current}/${total} ${normalizedHost}`);
    try {
        await fetchInstanceHealth(normalizedHost, options, "https:");
        store.markInstanceHealthOk(normalizedHost);
        console.log(`[instances-health] done ${normalizedHost}`);
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (isNoNetworkError(error)) {
            console.warn(`[instances-health] network issue ${normalizedHost}: ${message}`);
            return;
        }
        store.markInstanceHealthError(normalizedHost, message);
        console.warn(`[instances-health] error ${normalizedHost}: ${message}`);
    }
}
async function fetchInstanceHealth(host, options, protocol) {
    const url = buildHealthUrl(host, protocol);
    try {
        return await fetchJsonWithRetry(url, {
            timeoutMs: options.timeoutMs,
            maxRetries: options.maxRetries
        });
    }
    catch {
        const alternate = protocol === "https:" ? "http:" : "https:";
        const alternateUrl = buildHealthUrl(host, alternate);
        return await fetchJsonWithRetry(alternateUrl, {
            timeoutMs: options.timeoutMs,
            maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
        });
    }
}
function buildHealthUrl(host, protocol) {
    return `${protocol}//${host}/api/v1/video-channels?start=0&count=1`;
}
function parseOptionalNumber(value) {
    if (value === undefined || value === null || value === "")
        return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}
function parseOptionalHost(value) {
    if (typeof value !== "string")
        return null;
    const trimmed = value.trim().toLowerCase();
    return trimmed.length > 0 ? trimmed : null;
}
function computeMinAgeMs(options) {
    const days = Math.max(0, options.minAgeDays ?? 0);
    const mins = Math.max(0, options.minAgeMin ?? 0);
    const secs = Math.max(0, options.minAgeSec ?? 0);
    return (days * 24 * 60 * 60 * 1000 +
        mins * 60 * 1000 +
        secs * 1000);
}
function formatMinAgeLabel(options) {
    const parts = [];
    if (options.minAgeDays !== null)
        parts.push(`days=${options.minAgeDays}`);
    if (options.minAgeMin !== null)
        parts.push(`min=${options.minAgeMin}`);
    if (options.minAgeSec !== null)
        parts.push(`sec=${options.minAgeSec}`);
    return parts.length > 0 ? ` min_age(${parts.join(",")})` : "";
}
