import { setTimeout as sleep } from "node:timers/promises";
import Database from "better-sqlite3";
import { VideoStore } from "./db.js";
import { fetchJsonWithRetry, isNoNetworkError } from "./http.js";
const PAGE_SIZE = 50;
const CHANNEL_CONCURRENCY = 2;
const TAGS_CONCURRENCY = 4;
export async function crawlVideos(options) {
    if (options.updateTags) {
        await crawlVideoTags(options, "present");
        return;
    }
    if (options.tagsOnly) {
        await crawlVideoTags(options, "missing");
        return;
    }
    if (options.commentsOnly) {
        await crawlVideoComments(options);
        return;
    }
    const store = new VideoStore({ dbPath: options.dbPath });
    const existingDb = openExistingDb(options);
    const hostsAll = store.listInstances();
    const hosts = options.maxInstances > 0 ? hostsAll.slice(0, options.maxInstances) : hostsAll;
    const channelsAll = store.listChannelsWithVideos(1, hosts);
    const channels = options.maxChannels > 0
        ? channelsAll.slice(0, options.maxChannels)
        : channelsAll;
    const channelMeta = new Map(channels.map((channel) => [
        channel.channel_id,
        {
            channelSlug: channel.channel_name,
            displayName: channel.display_name,
            channelUrl: channel.channel_url
        }
    ]));
    store.setState("videos_new_total", "0");
    store.prepareVideoProgress(channels, options.resume);
    const statuses = (options.errorsOnly
        ? ["error"]
        : ["pending", "in_progress"]);
    const workItems = store.listVideoWorkItems(statuses);
    const grouped = groupByInstance(workItems);
    const instances = Array.from(grouped.keys());
    const workerCount = Math.min(options.concurrency, Math.max(1, instances.length));
    console.log(`[videos] instances=${instances.length} channels=${workItems.length} concurrency=${workerCount} resume=${options.resume} errorsOnly=${options.errorsOnly}`);
    try {
        const queue = instances.slice();
        const workers = Array.from({ length: workerCount }, () => workerLoop(queue, grouped, channelMeta, store, existingDb, options));
        await Promise.all(workers);
        const totalNew = Number(store.getState("videos_new_total") ?? 0);
        const totalNewText = Number.isFinite(totalNew) ? totalNew : 0;
        console.log(`[videos] finished new_total=${totalNewText}`);
    }
    finally {
        existingDb?.close();
        store.close();
    }
}
async function crawlVideoComments(options) {
    const store = new VideoStore({ dbPath: options.dbPath });
    const items = store.listVideosForComments(options.resume);
    const grouped = groupByInstanceComments(items);
    const instances = Array.from(grouped.keys());
    const workerCount = Math.min(options.concurrency, Math.max(1, instances.length));
    console.log(`[comments] instances=${instances.length} videos=${items.length} concurrency=${workerCount} resume=${options.resume}`);
    const queue = instances.slice();
    const workers = Array.from({ length: workerCount }, () => commentsWorkerLoop(queue, grouped, store, options));
    await Promise.all(workers);
    console.log("[comments] finished");
    store.close();
}
async function crawlVideoTags(options, mode) {
    const store = new VideoStore({ dbPath: options.dbPath });
    const items = store.listVideosForTags(mode);
    const grouped = groupByInstanceTags(items);
    const instances = Array.from(grouped.keys());
    const workerCount = Math.min(options.concurrency, Math.max(1, instances.length));
    console.log(`[tags] instances=${instances.length} videos=${items.length} concurrency=${workerCount}`);
    const queue = instances.slice();
    const workers = Array.from({ length: workerCount }, () => tagWorkerLoop(queue, grouped, store, options));
    await Promise.all(workers);
    console.log("[tags] finished");
    store.close();
}
async function workerLoop(queue, grouped, channelMeta, store, existingDb, options) {
    while (true) {
        const host = queue.pop();
        if (!host)
            return;
        const items = grouped.get(host);
        if (!items)
            continue;
        await processInstance(host, items, channelMeta, store, existingDb, options);
    }
}
async function processInstance(host, items, channelMeta, store, existingDb, options) {
    const normalizedHost = host.toLowerCase();
    console.log(`[videos] start ${normalizedHost} channels=${items.length}`);
    await mapWithConcurrency(items, CHANNEL_CONCURRENCY, async (item) => {
        const meta = channelMeta.get(item.channelId);
        await processChannel(normalizedHost, item, meta, store, existingDb, options);
    });
    console.log(`[videos] done ${normalizedHost}`);
}
async function commentsWorkerLoop(queue, grouped, store, options) {
    while (true) {
        const host = queue.pop();
        if (!host)
            return;
        const items = grouped.get(host);
        if (!items)
            continue;
        await processCommentsInstance(host, items, store, options);
    }
}
async function tagWorkerLoop(queue, grouped, store, options) {
    while (true) {
        const host = queue.pop();
        if (!host)
            return;
        const items = grouped.get(host);
        if (!items)
            continue;
        await processTagInstance(host, items, store, options);
    }
}
async function processTagInstance(host, items, store, options) {
    const normalizedHost = host.toLowerCase();
    console.log(`[tags] start ${normalizedHost} videos=${items.length}`);
    for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        try {
            const tagsJson = await fetchVideoTags(normalizedHost, item.videoUuid, options);
            if (tagsJson !== null) {
                store.updateVideoTags(item.videoId, normalizedHost, tagsJson);
            }
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            const status = extractHttpStatus(message);
            const code = extractErrorCode(error);
            if (status === 404) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "not_found");
            }
            else if (isNoNetworkError(error)) {
                throw error;
            }
            else if (isCertExpired(code, message)) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "cert_expired");
            }
            else if (isTlsError(code, message)) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "tls_error");
            }
            else if (isTimeoutError(code, message)) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "timeout");
            }
            else {
                store.updateVideoError(item.videoId, normalizedHost, message);
                console.warn(`[tags] error ${normalizedHost}/${item.videoUuid}: ${message}`);
            }
        }
        if (options.hostDelayMs > 0 && index < items.length - 1) {
            await sleep(options.hostDelayMs);
        }
    }
    console.log(`[tags] done ${normalizedHost}`);
}
async function processCommentsInstance(host, items, store, options) {
    const normalizedHost = host.toLowerCase();
    console.log(`[comments] start ${normalizedHost} videos=${items.length}`);
    for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        try {
            const commentsCount = await fetchVideoComments(normalizedHost, item.videoUuid, options);
            if (commentsCount !== null) {
                store.updateVideoComments(item.videoId, normalizedHost, commentsCount);
            }
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            const status = extractHttpStatus(message);
            const code = extractErrorCode(error);
            if (status === 404) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "not_found");
            }
            else if (isNoNetworkError(error)) {
                throw error;
            }
            else if (isCertExpired(code, message)) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "cert_expired");
            }
            else if (isTlsError(code, message)) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "tls_error");
            }
            else if (isTimeoutError(code, message)) {
                store.updateVideoInvalid(item.videoId, normalizedHost, "timeout");
            }
            else {
                store.updateVideoError(item.videoId, normalizedHost, message);
                console.warn(`[comments] error ${normalizedHost}/${item.videoUuid}: ${message}`);
            }
        }
        if (options.hostDelayMs > 0 && index < items.length - 1) {
            await sleep(options.hostDelayMs);
        }
    }
    console.log(`[comments] done ${normalizedHost}`);
}
async function processChannel(host, item, meta, store, existingDb, options) {
    const channelSlug = item.channelName ?? meta?.channelSlug ?? null;
    if (!channelSlug) {
        store.updateVideoProgress(host, item.channelId, "error", item.lastStart, "missing channel slug");
        console.warn(`[videos] skip ${host}/${item.channelId} missing channel slug`);
        return;
    }
    const startAt = item.status === "in_progress" ? item.lastStart : 0;
    store.updateVideoProgress(host, item.channelId, "in_progress", startAt, null);
    console.log(`[videos] channel ${host}/${channelSlug} resume=${item.status} start=${startAt}`);
    try {
        const { localCount, totalCount } = await crawlChannelVideos(host, {
            channelId: item.channelId,
            channelSlug,
            displayName: meta?.displayName ?? null,
            channelUrl: meta?.channelUrl ?? null
        }, startAt, store, existingDb, options);
        store.updateVideoProgress(host, item.channelId, "done", 0, null);
        store.incrementState("videos_new_total", localCount);
        console.log(`[videos] channel done ${host}/${channelSlug} new=${localCount} total=${totalCount}`);
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        store.updateVideoProgress(host, item.channelId, "error", startAt, message);
        console.warn(`[videos] channel error ${host}/${channelSlug}: ${message}`);
    }
}
async function crawlChannelVideos(host, channel, startAt, store, existingDb, options) {
    let start = startAt;
    let protocol = "https:";
    let totalCount = 0;
    let localCount = 0;
    let fullPagesSeen = 0;
    let pagesFetched = 0;
    while (true) {
        const { page, protocol: usedProtocol } = await fetchPage(host, channel.channelSlug, start, options, protocol);
        protocol = usedProtocol;
        pagesFetched += 1;
        const data = Array.isArray(page.data) ? page.data : [];
        const ids = options.newOnly
            ? Array.from(new Set(data
                .map((video) => toStringId(video.uuid ?? video.id))
                .filter((value) => Boolean(value))))
            : [];
        const existingIds = options.newOnly ? store.listExistingVideoIds(host, ids) : null;
        const externalExistingIds = options.newOnly
            ? queryExternalExistingVideoIds(existingDb, host, ids)
            : null;
        const nextStart = start + PAGE_SIZE;
        totalCount += data.length;
        if (data.length > 0) {
            const checkedAt = Date.now();
            const rows = [];
            for (const video of data) {
                if (existingIds) {
                    const id = toStringId(video.uuid ?? video.id);
                    if (id &&
                        (existingIds.has(id) ||
                            (externalExistingIds ? externalExistingIds.has(id) : false))) {
                        continue;
                    }
                }
                const row = toVideoRow(video, host, protocol, channel, checkedAt);
                if (!row)
                    continue;
                rows.push(row);
            }
            localCount += rows.length;
            store.upsertVideos(rows);
        }
        store.updateVideoProgress(host, channel.channelId, "in_progress", nextStart, null);
        if (options.newOnly &&
            options.stopAfterFullPages > 0 &&
            ids.length > 0 &&
            existingIds &&
            existingIds.size + (externalExistingIds?.size ?? 0) >= ids.length) {
            fullPagesSeen += 1;
            if (fullPagesSeen >= options.stopAfterFullPages) {
                console.log(`[videos] stop ${host}/${channel.channelSlug} full_pages=${fullPagesSeen} page_start=${start}`);
                break;
            }
        }
        else {
            fullPagesSeen = 0;
        }
        if (page.total !== undefined) {
            if (nextStart >= page.total)
                break;
        }
        else if (data.length < PAGE_SIZE) {
            break;
        }
        if (options.maxVideosPages > 0 && pagesFetched >= options.maxVideosPages) {
            break;
        }
        start = nextStart;
    }
    return { localCount, totalCount };
}
async function fetchPage(host, channelName, start, options, protocol) {
    const primaryUrl = buildChannelVideosUrl(host, channelName, start, PAGE_SIZE, protocol, options.sort);
    try {
        const page = await fetchJsonWithRetry(primaryUrl, {
            timeoutMs: options.timeoutMs,
            maxRetries: options.maxRetries
        });
        return { page, protocol };
    }
    catch {
        const fallbackProtocol = protocol === "https:" ? "http:" : "https:";
        const alternateUrl = buildChannelVideosUrl(host, channelName, start, PAGE_SIZE, fallbackProtocol, options.sort);
        const page = await fetchJsonWithRetry(alternateUrl, {
            timeoutMs: options.timeoutMs,
            maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
        });
        return { page, protocol: fallbackProtocol };
    }
}
function buildChannelVideosUrl(host, channelName, start, count, protocol, sort) {
    const safeSort = sort && sort.trim().length > 0 ? sort.trim() : "-publishedAt";
    return `${protocol}//${host}/api/v1/video-channels/${encodeURIComponent(channelName)}/videos?start=${start}&count=${count}&sort=${encodeURIComponent(safeSort)}`;
}
function toVideoRow(video, host, protocol, channel, checkedAt) {
    const videoId = toStringId(video.uuid ?? video.id);
    if (!videoId)
        return null;
    const channelRef = video.channel;
    const account = video.account ?? channelRef?.account ?? channelRef?.ownerAccount ?? null;
    const channelName = channel.displayName ?? toNullableString(channelRef?.displayName ?? channelRef?.display_name);
    const channelUrl = toNullableString(channelRef?.url) ?? channel.channelUrl ?? null;
    const videoUrl = toNullableString(video.url);
    const thumbnailUrl = resolveAssetUrl(video.thumbnailUrl ?? video.thumbnailPath ?? video.thumbnail_path ?? video.thumbnail, host, protocol);
    return {
        videoId,
        videoUuid: toNullableString(video.uuid),
        videoNumericId: toNullableNumber(video.id),
        instanceDomain: host,
        channelId: channel.channelId,
        channelName,
        channelUrl,
        accountName: toNullableString(account?.displayName ?? account?.display_name ?? account?.name),
        accountUrl: toNullableString(account?.url),
        title: toNullableString(video.name ?? video.title),
        description: toNullableString(video.description),
        tagsJson: null,
        category: extractCategory(video.category),
        publishedAt: toNullableTimestamp(video.publishedAt ?? video.published_at ?? video.createdAt ?? video.created_at),
        videoUrl,
        duration: toNullableNumber(video.duration),
        thumbnailUrl,
        embedPath: toNullableString(video.embedPath ?? video.embed_path),
        views: toNullableNumber(video.views ?? video.views_count),
        likes: toNullableNumber(video.likes ?? video.likes_count),
        dislikes: toNullableNumber(video.dislikes ?? video.dislikes_count),
        commentsCount: null,
        nsfw: toNullableBoolean(video.nsfw),
        previewPath: toNullableString(video.previewPath ?? video.preview_path),
        lastCheckedAt: checkedAt
    };
}
function groupByInstance(items) {
    const grouped = new Map();
    for (const item of items) {
        const list = grouped.get(item.instanceDomain) ?? [];
        list.push(item);
        grouped.set(item.instanceDomain, list);
    }
    return grouped;
}
function groupByInstanceTags(items) {
    const grouped = new Map();
    for (const item of items) {
        const list = grouped.get(item.instanceDomain) ?? [];
        list.push(item);
        grouped.set(item.instanceDomain, list);
    }
    return grouped;
}
function groupByInstanceComments(items) {
    const grouped = new Map();
    for (const item of items) {
        const list = grouped.get(item.instanceDomain) ?? [];
        list.push(item);
        grouped.set(item.instanceDomain, list);
    }
    return grouped;
}
async function mapWithConcurrency(items, concurrency, mapper) {
    if (items.length === 0)
        return;
    const limit = Math.max(1, concurrency);
    let index = 0;
    const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
        while (true) {
            const current = index;
            index += 1;
            if (current >= items.length)
                return;
            await mapper(items[current]);
        }
    });
    await Promise.all(workers);
}
function toNullableString(value) {
    return typeof value === "string" && value.length > 0 ? value : null;
}
function toNullableNumber(value) {
    if (typeof value === "number" && Number.isFinite(value))
        return value;
    if (typeof value === "string" && value.length > 0) {
        const parsed = Number(value);
        if (Number.isFinite(parsed))
            return parsed;
    }
    return null;
}
function toNullableTimestamp(value) {
    if (typeof value === "number" && Number.isFinite(value))
        return value;
    if (typeof value === "string" && value.length > 0) {
        const parsed = Date.parse(value);
        if (!Number.isNaN(parsed))
            return parsed;
    }
    return null;
}
function toNullableBoolean(value) {
    if (typeof value === "boolean")
        return value ? 1 : 0;
    return null;
}
function toTagsJson(value) {
    if (!Array.isArray(value))
        return null;
    const tags = value.filter((tag) => typeof tag === "string");
    return JSON.stringify(tags);
}
function toCommentsCount(value) {
    return toNullableNumber(value);
}
function toStringId(value) {
    if (typeof value === "string" && value.length > 0)
        return value;
    if (typeof value === "number" && Number.isFinite(value))
        return String(value);
    return null;
}
function extractCategory(value) {
    if (typeof value === "string" && value.length > 0)
        return value;
    if (typeof value === "number" && Number.isFinite(value))
        return String(value);
    if (value && typeof value === "object") {
        const label = toNullableString(value.label ?? value.name);
        if (label)
            return label;
        const id = toStringId(value.id);
        if (id)
            return id;
    }
    return null;
}
function resolveAssetUrl(value, host, protocol) {
    const candidate = extractAssetValue(value);
    if (!candidate)
        return null;
    if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
        return candidate;
    }
    if (candidate.startsWith("/")) {
        return `${protocol}//${host}${candidate}`;
    }
    return `${protocol}//${host}/${candidate}`;
}
function extractAssetValue(value) {
    if (typeof value === "string" && value.length > 0)
        return value;
    if (value && typeof value === "object") {
        const asset = value;
        return (toNullableString(asset.url) ??
            toNullableString(asset.path) ??
            toNullableString(asset.staticPath));
    }
    return null;
}
async function fetchVideoDetail(host, videoUuid, options, protocol) {
    const primaryUrl = buildVideoDetailUrl(host, videoUuid, protocol);
    try {
        return await fetchJsonWithRetry(primaryUrl, {
            timeoutMs: options.timeoutMs,
            maxRetries: options.maxRetries
        });
    }
    catch {
        const fallbackProtocol = protocol === "https:" ? "http:" : "https:";
        const alternateUrl = buildVideoDetailUrl(host, videoUuid, fallbackProtocol);
        return await fetchJsonWithRetry(alternateUrl, {
            timeoutMs: options.timeoutMs,
            maxRetries: Math.max(1, Math.floor(options.maxRetries / 2))
        });
    }
}
async function fetchVideoTags(host, videoUuid, options) {
    const detail = await fetchVideoDetail(host, videoUuid, options, "https:");
    return toTagsJson(detail.tags);
}
async function fetchVideoComments(host, videoUuid, options) {
    const detail = await fetchVideoDetail(host, videoUuid, options, "https:");
    return toCommentsCount(detail.comments ?? detail.commentsCount ?? detail.comments_count);
}
function buildVideoDetailUrl(host, videoUuid, protocol) {
    return `${protocol}//${host}/api/v1/videos/${encodeURIComponent(videoUuid)}`;
}
function openExistingDb(options) {
    if (!options.existingDbPath || options.existingDbPath.trim().length === 0) {
        return null;
    }
    return new Database(options.existingDbPath, {
        readonly: true,
        fileMustExist: true
    });
}
function queryExternalExistingVideoIds(db, instanceDomain, ids) {
    if (!db || ids.length === 0)
        return new Set();
    const placeholders = ids.map(() => "?").join(", ");
    const rows = db
        .prepare(`SELECT video_id
       FROM videos
       WHERE instance_domain = ?
         AND video_id IN (${placeholders})`)
        .all(instanceDomain, ...ids);
    return new Set(rows.map((row) => row.video_id));
}
function extractHttpStatus(message) {
    const match = message.match(/HTTP (\d{3})/);
    if (!match)
        return null;
    return Number(match[1]);
}
function extractErrorCode(error) {
    if (!error || typeof error !== "object")
        return null;
    const err = error;
    return err.cause?.code ?? err.code ?? null;
}
function isCertExpired(code, message) {
    if (typeof code === "string" && code.toUpperCase() === "CERT_HAS_EXPIRED")
        return true;
    return message.toLowerCase().includes("certificate has expired");
}
function isTlsError(code, message) {
    if (typeof code === "string") {
        const upper = code.toUpperCase();
        if (upper.includes("CERT") || upper.includes("SSL") || upper.includes("TLS")) {
            return true;
        }
    }
    const lowered = message.toLowerCase();
    return lowered.includes("certificate") || lowered.includes("ssl") || lowered.includes("tls");
}
function isTimeoutError(code, message) {
    if (typeof code === "string") {
        const upper = code.toUpperCase();
        if (upper.includes("TIMEOUT")) {
            return true;
        }
    }
    return message.toLowerCase().includes("timeout");
}
