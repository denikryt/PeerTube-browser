/** Fatal transport observations must stop sibling parent work across nested host queues. */
import assert from "node:assert/strict";
import test from "node:test";
import { ChannelStore } from "../../src/db/channels.js";
import { NoNetworkError } from "../../src/http.js";
import { crawlChannelVideosCount } from "../../src/channels-videos-count-worker.js";
import { checkChannelHealth, type ChannelCrawlOptions } from "../../src/channels-worker.js";
import { crawlHostPipeline } from "../../src/host-pipeline-worker.js";
import { checkInstancesHealth } from "../../src/instances-health-cli.js";
import { createTempDb, getRow } from "./helpers.js";

/** Exercise actual repository/worker/limiter boundaries with only fetch substituted. */
function parents(health: boolean) {
  const temp = createTempDb("parent-outage-siblings");
  const store = new ChannelStore({ dbPath: temp.dbPath });
  const hosts = ["a.example", "b.example"];
  for (const host of hosts) {
    store.markInstanceHealthOk(host);
    store.upsertChannels(Array.from({ length: 5 }, (_, i) => ({
      channelId: String(i), channelName: `channel_${i}`,
      instanceDomain: host, channelUrl: null, displayName: null,
      videosCount: null, followersCount: 0, avatarUrl: null,
    })));
  }
  store.initializeParentEnumeration(hosts);
  for (const host of hosts) {
    store.markInstanceHealthOk(host);
    store.updateChannelProgress(host, "done", 0);
    if (!health) for (let i = 0; i < 5; i++) store.updateChannelHealthOk(String(i), host);
  }
  store.close();
  const options: ChannelCrawlOptions = {
    dbPath: temp.dbPath, hostsFile: null, excludeHostsFile: null,
    concurrency: 2, hostConcurrency: 1, hostDelayMs: 0,
    timeoutMs: 1000, maxRetries: 0, resume: false, errorsOnly: false,
    newOnly: false, maxInstances: 0, maxChannels: 0,
  };
  return { ...temp, options };
}

for (const mode of ["counts", "health"] as const) {
  test(`${mode}: local outage stops sibling requests after in-flight work drains`, async () => {
    const f = parents(mode === "health"), previous = globalThis.fetch;
    const requests: Array<{ host: string; afterFatal: boolean }> = [];
    let fatal = false;
    let releaseA!: () => void;
    const aStarted = new Promise<void>((resolve) => { releaseA = resolve; });
    try {
      globalThis.fetch = async (input) => {
        const host = new URL(String(input)).hostname;
        requests.push({ host, afterFatal: fatal });
        if (host === "b.example") {
          await aStarted;
          fatal = true;
          throw new NoNetworkError("confirmed local outage timeout");
        }
        releaseA();
        // Give B a chance to publish its fatal signal while A's request is in flight.
        await new Promise<void>((resolve) => setTimeout(resolve, 12));
        return new Response('{"total":0,"data":[]}');
      };
      await assert.rejects(
        mode === "counts" ? crawlChannelVideosCount(f.options) : checkChannelHealth(f.options),
        NoNetworkError,
      );
      assert.ok(requests.some((r) => r.host === "a.example"));
      assert.ok(requests.some((r) => r.host === "b.example"));
      assert.equal(requests.filter((r) => r.afterFatal).length, 0, JSON.stringify(requests));
      // The pre-fatal in-flight response can persist; no later channel was fetched.
      const count = getRow<{ n: number }>(f.dbPath,
        mode === "counts"
          ? "SELECT COUNT(*) n FROM channels WHERE instance_domain='a.example' AND videos_count=0"
          : "SELECT COUNT(*) n FROM channels WHERE instance_domain='a.example' AND health_status='ok'",
      );
      assert.equal(count.n, 1);
    } finally {
      globalThis.fetch = previous;
      f.cleanup();
    }
  });

  test(`${mode}: remote HTTP failure stays host-local`, async () => {
    const f = parents(mode === "health"), previous = globalThis.fetch;
    let aRequests = 0;
    try {
      globalThis.fetch = async (input) => {
        const host = new URL(String(input)).hostname;
        if (host === "b.example") return new Response("missing", { status: 404 });
        aRequests++;
        return new Response('{"total":0,"data":[]}');
      };
      await (mode === "counts" ? crawlChannelVideosCount(f.options) : checkChannelHealth(f.options));
      assert.equal(aRequests, 5);
    } finally {
      globalThis.fetch = previous;
      f.cleanup();
    }
  });
}

test("host pipeline shares fatal signal between concurrent stages", async () => {
  const f = createTempDb("pipeline-outage-siblings"), previous = globalThis.fetch;
  const store = new ChannelStore({ dbPath: f.dbPath });
  for (const host of ["a.example", "b.example"]) store.markInstanceHealthOk(host);
  store.close();
  const requests: Array<{ host: string; afterFatal: boolean }> = [];
  let fatal = false;
  try {
    globalThis.fetch = async (input) => {
      const url = new URL(String(input));
      requests.push({ host: url.hostname, afterFatal: fatal });
      if (url.pathname === "/api/v1/video-channels") {
        return new Response(JSON.stringify(url.searchParams.get("count") === "1"
          ? { total: 0, data: [] }
          : { total: 3, data: Array.from({ length: 3 }, (_, i) => ({ id: i + 1, name: `channel_${i}`, host: url.hostname })) }));
      }
      if (url.hostname === "b.example") {
        await new Promise<void>((resolve) => setTimeout(resolve, 5));
        fatal = true;
        throw new NoNetworkError("confirmed local outage timeout");
      }
      await new Promise<void>((resolve) => setTimeout(resolve, 25));
      return new Response('{"total":0,"data":[]}');
    };
    const options: ChannelCrawlOptions = {
      dbPath: f.dbPath, hostsFile: null, excludeHostsFile: null,
      concurrency: 2, hostConcurrency: 1, hostDelayMs: 0,
      timeoutMs: 1000, maxRetries: 0, resume: false, errorsOnly: false,
      newOnly: false, maxInstances: 0, maxChannels: 0,
    };
    await assert.rejects(crawlHostPipeline({
      channels: options, counts: options,
      videos: { ...options, existingDbPath: null, newOnly: true,
        stopAfterFullPages: 0, sort: "-publishedAt", maxVideosPages: 1,
        tagsOnly: false, updateTags: false, commentsOnly: false, refreshThumbnails: false },
    }), NoNetworkError);
    assert.ok(requests.some((r) => r.host === "a.example"));
    assert.equal(requests.filter((r) => r.afterFatal).length, 0);
  } finally {
    globalThis.fetch = previous;
    f.cleanup();
  }
});


test("instance probe does not schedule further hosts after an outage", async () => {
  const f = createTempDb("probe-outage-siblings"), previous = globalThis.fetch;
  const store = new ChannelStore({ dbPath: f.dbPath });
  for (const host of ["a.example", "b.example", "c.example"]) store.markInstanceHealthOk(host);
  store.close();
  let fatal = false;
  let releaseA!: () => void;
  const aStarted = new Promise<void>((resolve) => { releaseA = resolve; });
  const requests: Array<{ host: string; afterFatal: boolean }> = [];
  try {
    globalThis.fetch = async (input) => {
      const host = new URL(String(input)).hostname;
      requests.push({ host, afterFatal: fatal });
      if (host === "b.example") {
        await aStarted;
        fatal = true;
        throw new NoNetworkError("confirmed local outage timeout");
      }
      releaseA();
      await new Promise<void>((resolve) => setTimeout(resolve, 15));
      return new Response('{"total":0,"data":[]}');
    };
    await assert.rejects(checkInstancesHealth({
      dbPath: f.dbPath, concurrency: 2, hostDelayMs: 0, timeoutMs: 1000,
      maxRetries: 0, minAgeDays: null, minAgeMin: null, minAgeSec: null,
      hostsFile: null, host: null, errorsOnly: false,
    }), NoNetworkError);
    assert.equal(requests.filter((r) => r.afterFatal).length, 0, JSON.stringify(requests));
    assert.ok(requests.some((r) => r.host === "b.example"));
  } finally {
    globalThis.fetch = previous;
    f.cleanup();
  }
});
