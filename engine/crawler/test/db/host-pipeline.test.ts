/** Behavior tests for host-level crawler pipeline scheduling. */

import assert from "node:assert/strict";
import test from "node:test";

import { ChannelStore } from "../../src/db/channels.js";
import { VideoStore } from "../../src/db/videos.js";
import { runHostPipelineHosts } from "../../src/host-pipeline-worker.js";
import { stopWork, type WorkCancellation } from "../../src/work-cancellation.js";
import { createTempDb, execSql } from "./helpers.js";

test("host pipeline starts videos for a ready host while another host is still counting", async () => {
  const events: string[] = [];
  let releaseSlowCount!: () => void;
  const slowCount = new Promise<void>((resolve) => {
    releaseSlowCount = resolve;
  });

  const running = runHostPipelineHosts([
    "slow.example",
    "fast.example"
  ], 2, {
    channels: async (host) => {
      events.push(`${host}:channels`);
    },
    counts: async (host) => {
      events.push(`${host}:counts`);
      if (host === "slow.example") await slowCount;
    },
    videos: async (host) => {
      events.push(`${host}:videos`);
    }
  });

  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.ok(events.includes("fast.example:videos"));
  assert.ok(!events.includes("slow.example:videos"));

  releaseSlowCount();
  await running;
  assert.deepEqual(
    events.filter((event) => event.startsWith("slow.example")),
    ["slow.example:channels", "slow.example:counts", "slow.example:videos"]
  );
});

test("host pipeline rechecks global stage priority after every completed stage", async () => {
  const events: string[] = [];

  await runHostPipelineHosts([
    "channels-a.example", "channels-b.example", "counts.example", "videos.example"
  ], 1, {
    channels: async (host) => {
      events.push(`${host}:channels`);
    },
    counts: async (host) => {
      events.push(`${host}:counts`);
    },
    videos: async (host) => {
      events.push(`${host}:videos`);
    }
  });

  assert.deepEqual(events, [
    "channels-a.example:channels",
    "channels-b.example:channels",
    "counts.example:channels",
    "videos.example:channels",
    "channels-a.example:counts",
    "channels-b.example:counts",
    "counts.example:counts",
    "videos.example:counts",
    "channels-a.example:videos",
    "channels-b.example:videos",
    "counts.example:videos",
    "videos.example:videos"
  ]);
});

test("host pipeline prioritizes channel lists, then missing counts, then videos", () => {
  const temp = createTempDb("crawler-host-pipeline-priority");
  const hosts = [
    "channels.example",
    "counts.example",
    "videos.example",
    "complete.example"
  ];
  try {
    const channels = new ChannelStore({ dbPath: temp.dbPath });
    for (const host of hosts) channels.markInstanceDone(host);
    channels.upsertChannels([
      {
        channelId: "counts", channelName: "counts", channelUrl: null, displayName: null,
        instanceDomain: "counts.example", videosCount: null, followersCount: 0, avatarUrl: null
      },
      {
        channelId: "videos", channelName: "videos", channelUrl: null, displayName: null,
        instanceDomain: "videos.example", videosCount: 2, followersCount: 0, avatarUrl: null
      },
      {
        channelId: "complete", channelName: "complete", channelUrl: null, displayName: null,
        instanceDomain: "complete.example", videosCount: 1, followersCount: 0, avatarUrl: null
      }
    ]);
    channels.prepareChannelProgress(hosts, false);
    for (const host of ["counts.example", "videos.example", "complete.example"]) {
      channels.updateChannelProgress(host, "done", 0);
    }
    channels.close();

    // A legacy progress row is not fresh provenance. Model a staging database
    // whose crawl_state table exists but has no page-zero host stamp.
    execSql(temp.dbPath,
      "CREATE TABLE IF NOT EXISTS crawl_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
    const videos = new VideoStore({ dbPath: temp.dbPath });
    // Old done does not make an unprobed parent eligible for fresh video work.
    assert.deepEqual(videos.listChannelsWithVideos(1, ["videos.example", "complete.example"]), []);
    videos.close();

    const fresh = new ChannelStore({ dbPath: temp.dbPath });
    // All previously classified hosts must instead be initialized for a new
    // parent observation and page-zero traversal in the next normal run.
    fresh.initializeParentEnumeration(hosts);
    assert.deepEqual(fresh.listFreshHealthyHosts(hosts), []);
    fresh.close();
  } finally {
    temp.cleanup();
  }
});

test("scheduler stops only the host whose stage cannot advance",async()=>{
 const events:string[]=[];
 await runHostPipelineHosts(['incomplete.example','complete.example'],2,{
  channels:async host=>{events.push('channels:'+host);return host==='complete.example'},
  counts:async host=>{events.push('counts:'+host)},
  videos:async host=>{events.push('videos:'+host)}
 });
 assert.ok(events.includes('counts:complete.example'));
 assert.ok(events.includes('videos:complete.example'));
 assert.ok(!events.includes('counts:incomplete.example'));
 assert.ok(!events.includes('videos:incomplete.example'));
});


test("host scheduler preserves the first fatal reason and drains sibling work", async () => {
  const firstError = new Error("first host failed");
  const events: string[] = [];
  const cancellation: WorkCancellation = { stopped: false };
  let releaseActive!: () => void;
  const activeHost = new Promise<void>((resolve) => { releaseActive = resolve; });

  // The sibling is already executing when the other host fails synchronously.
  const running = runHostPipelineHosts(["active.example", "failed.example", "queued.example"], 2, {
    channels: async (host) => {
      events.push(`channels:${host}`);
      if (host === "active.example") await activeHost;
      if (host === "failed.example") throw firstError;
    },
    counts: async (host) => { events.push(`counts:${host}`); },
    videos: async (host) => { events.push(`videos:${host}`); }
  }, cancellation);

  let settled = false;
  void running.finally(() => { settled = true; }).catch(() => {});
  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.equal(cancellation.stopped, true);
  assert.equal(cancellation.reason, firstError);
  assert.equal(settled, false, "caller must wait for an in-flight sibling");
  assert.deepEqual(events, ["channels:active.example", "channels:failed.example"]);

  releaseActive();
  await assert.rejects(running, (error: unknown) => error === firstError);
  assert.deepEqual(events, ["channels:active.example", "channels:failed.example"]);
});

test("host scheduler retains an earlier nested cancellation reason", async () => {
  const original = new Error("local network outage");
  const secondary = new Error("wrapper failure");
  const cancellation: WorkCancellation = { stopped: false };
  const events: string[] = [];

  // A nested worker publishes an outage before its stage reports its own error.
  await assert.rejects(runHostPipelineHosts(["fatal.example", "queued.example"], 1, {
    channels: async (host) => {
      events.push(`channels:${host}`);
      stopWork(cancellation, original);
      throw secondary;
    },
    counts: async (host) => { events.push(`counts:${host}`); },
    videos: async (host) => { events.push(`videos:${host}`); }
  }, cancellation), (error: unknown) => error === original);
  assert.deepEqual(events, ["channels:fatal.example"]);
  assert.equal(cancellation.reason, original);
});

test("host scheduler honors cancellation published while a stage is active", async () => {
  const reason = new Error("cancel sibling host");
  const cancellation: WorkCancellation = { stopped: false };
  const events: string[] = [];
  let releaseActive!: () => void;
  const activeHost = new Promise<void>((resolve) => { releaseActive = resolve; });
  const running = runHostPipelineHosts(["active.example", "queued.example"], 1, {
    channels: async (host) => {
      events.push(`channels:${host}`);
      await activeHost;
    },
    counts: async (host) => { events.push(`counts:${host}`); },
    videos: async (host) => { events.push(`videos:${host}`); }
  }, cancellation);

  await new Promise<void>((resolve) => setImmediate(resolve));
  stopWork(cancellation, reason);
  releaseActive();
  await assert.rejects(running, (error: unknown) => error === reason);
  assert.deepEqual(events, ["channels:active.example"]);
});

test("host scheduler does not replace the first error when a second host later fails", async () => {
  const first = new Error("first host failure");
  const later = new Error("later host failure");
  const cancellation: WorkCancellation = { stopped: false };
  let releaseLater!: () => void;
  const waiting = new Promise<void>((resolve) => { releaseLater = resolve; });
  const events: string[] = [];

  const running = runHostPipelineHosts(["first.example", "later.example", "queued.example"], 2, {
    channels: async (host) => {
      events.push(`channels:${host}`);
      if (host === "first.example") throw first;
      if (host === "later.example") {
        await waiting;
        throw later;
      }
    },
    counts: async (host) => { events.push(`counts:${host}`); },
    videos: async (host) => { events.push(`videos:${host}`); }
  }, cancellation);

  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.equal(cancellation.reason, first);
  releaseLater();
  await assert.rejects(running, (error: unknown) => error === first);
  assert.deepEqual(events, ["channels:first.example", "channels:later.example"]);
});
