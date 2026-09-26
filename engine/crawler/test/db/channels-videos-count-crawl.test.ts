/** Scenario coverage for retrying persisted channel video-count failures. */

import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import { crawlChannelVideosCount } from "../../src/channels-videos-count-worker.js";
import { ChannelStore } from "../../src/db/channels.js";
import { createTempDb, getRow } from "./helpers.js";

test("error-only count crawl retries an error even when resume is enabled", async () => {
  const temp = createTempDb("crawler-count-error-retry");
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ total: 7, data: [] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;
  const store = new ChannelStore({ dbPath: temp.dbPath });
  store.markInstanceDone(host);
  store.upsertChannels([{
    channelId: "c1",
    channelName: "music",
    channelUrl: `http://${host}/video-channels/music`,
    displayName: "Music",
    instanceDomain: host,
    videosCount: null,
    followersCount: 0,
    avatarUrl: null
  }]);
  store.updateChannelVideosCountError("c1", host, "[timeout] prior failure");
  store.close();

  try {
    await crawlChannelVideosCount({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      concurrency: 1,
      hostConcurrency: 1,
      hostDelayMs: 0,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: true,
      errorsOnly: true
    });
    assert.deepEqual(
      getRow<{ videos_count: number; last_error: string | null }>(
        temp.dbPath,
        "SELECT videos_count, last_error FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        host
      ),
      { videos_count: 7, last_error: null }
    );
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});

test("normal count resume requests only channels whose count is still missing", async () => {
  const temp = createTempDb("crawler-count-resume-missing");
  const requestedChannels: string[] = [];
  const server = http.createServer((request, response) => {
    const match = (request.url ?? "").match(/video-channels\/([^/]+)\/videos/);
    if (match) requestedChannels.push(match[1]);
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ total: 3, data: [] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;
  const store = new ChannelStore({ dbPath: temp.dbPath });
  store.markInstanceDone(host);
  store.upsertChannels([
    {
      channelId: "done",
      channelName: "already-counted",
      channelUrl: `http://${host}/video-channels/already-counted`,
      displayName: "Done",
      instanceDomain: host,
      videosCount: 8,
      followersCount: 0,
      avatarUrl: null
    },
    {
      channelId: "pending",
      channelName: "missing-count",
      channelUrl: `http://${host}/video-channels/missing-count`,
      displayName: "Pending",
      instanceDomain: host,
      videosCount: null,
      followersCount: 0,
      avatarUrl: null
    }
  ]);
  store.close();

  try {
    await crawlChannelVideosCount({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      concurrency: 1,
      hostConcurrency: 1,
      hostDelayMs: 0,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: true,
      errorsOnly: false
    });

    assert.deepEqual(requestedChannels, ["missing-count"]);
    assert.equal(
      getRow<{ videos_count: number }>(
        temp.dbPath,
        "SELECT videos_count FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "pending",
        host
      ).videos_count,
      3
    );
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});
