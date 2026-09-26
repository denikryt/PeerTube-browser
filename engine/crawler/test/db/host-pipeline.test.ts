/** Behavior tests for host-level crawler pipeline scheduling. */

import assert from "node:assert/strict";
import test from "node:test";

import { ChannelStore } from "../../src/db/channels.js";
import { HostPipelineStore } from "../../src/db/host-pipeline.js";
import { VideoStore } from "../../src/db/videos.js";
import { runHostPipelineHosts } from "../../src/host-pipeline-worker.js";
import { createTempDb } from "./helpers.js";

test("host pipeline starts videos for a ready host while another host is still counting", async () => {
  const events: string[] = [];
  let releaseSlowCount!: () => void;
  const slowCount = new Promise<void>((resolve) => {
    releaseSlowCount = resolve;
  });

  const running = runHostPipelineHosts([
    { host: "slow.example", stage: "channels" },
    { host: "fast.example", stage: "channels" }
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
    { host: "channels-a.example", stage: "channels" },
    { host: "channels-b.example", stage: "channels" },
    { host: "counts.example", stage: "counts" },
    { host: "videos.example", stage: "videos" }
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
    "counts.example:counts",
    "channels-a.example:counts",
    "channels-b.example:counts",
    "videos.example:videos",
    "counts.example:videos",
    "channels-a.example:videos",
    "channels-b.example:videos"
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

    const videos = new VideoStore({ dbPath: temp.dbPath });
    const positive = videos.listChannelsWithVideos(1, ["videos.example", "complete.example"]);
    videos.prepareVideoProgress(positive, false);
    videos.updateVideoProgress("complete.example", "complete", "done", 0, null);
    videos.close();

    const priority = new HostPipelineStore(temp.dbPath);
    assert.deepEqual(priority.listPendingHosts(hosts), [
      { host: "channels.example", stage: "channels" },
      { host: "counts.example", stage: "counts" },
      { host: "videos.example", stage: "videos" }
    ]);
    priority.close();
  } finally {
    temp.cleanup();
  }
});
