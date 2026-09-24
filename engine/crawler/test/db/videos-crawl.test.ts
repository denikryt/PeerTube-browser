/**
 * Scenario tests for the end-to-end video crawl path.
 *
 * These tests run the real crawler worker against a tiny local HTTP server so
 * persisted video rows prove which PeerTube payload won during ingestion.
 */

import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import { ChannelStore } from "../../src/db/channels.js";
import { VideoStore } from "../../src/db/videos.js";
import { crawlVideos } from "../../src/videos-worker.js";
import { createTempDb, execSql, getRow } from "./helpers.js";

/**
 * Start a minimal PeerTube-like HTTP server for one crawl scenario.
 */
async function startPeerTubeFixtureServer() {
  const requests: string[] = [];
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    requests.push(url.pathname);

    if (url.pathname === "/api/v1/video-channels/music/videos") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          total: 1,
          data: [
            {
              id: 1,
              uuid: "uuid-1",
              name: "Song",
              description: "List payload keeps stale media",
              url: "http://HOST/w/uuid-1",
              thumbnailUrl: "http://HOST/lazy-static/thumbnails/stale.jpg",
              previewPath: "/lazy-static/previews/stale.jpg",
              embedPath: "/videos/embed/uuid-1",
              duration: 60,
              channel: {
                id: "c1",
                name: "music",
                displayName: "Music",
                url: "http://HOST/video-channels/music"
              }
            }
          ]
        })
      );
      return;
    }

    if (url.pathname === "/api/v1/videos/uuid-1") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          thumbnailPath: "/lazy-static/thumbnails/fresh.jpg",
          previewPath: "/lazy-static/previews/fresh.jpg"
        })
      );
      return;
    }

    response.writeHead(404, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: "not found" }));
  });

  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve());
  });

  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;

  return {
    host,
    requests,
    close: async () => {
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    }
  };
}

/**
 * Seed one crawlable channel for the scenario test.
 */
function seedChannel(dbPath: string, host: string, videosCount: number | null = 1) {
  const channels = new ChannelStore({ dbPath });
  channels.markInstanceDone(host);
  channels.upsertChannels([
    {
      channelId: "c1",
      channelName: "music",
      channelUrl: `http://${host}/video-channels/music`,
      displayName: "Music",
      instanceDomain: host,
      videosCount,
      followersCount: 10,
      avatarUrl: null
    }
  ]);
  channels.close();
}

test("crawlVideos stores refreshed count and metadata for a channel known to have videos", async () => {
  const temp = createTempDb("crawler-videos-single-pass");
  const fixture = await startPeerTubeFixtureServer();

  try {
    seedChannel(temp.dbPath, fixture.host, 1);

    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 2000,
      maxRetries: 0,
      resume: true,
      errorsOnly: false,
      newOnly: true,
      stopAfterFullPages: 2,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 0,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });

    assert.equal(
      getRow<{ videos_count: number }>(
        temp.dbPath,
        "SELECT videos_count FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        fixture.host
      ).videos_count,
      1
    );
    assert.equal(
      getRow<{ count: number }>(
        temp.dbPath,
        "SELECT COUNT(*) AS count FROM videos WHERE video_id = ? AND instance_domain = ?",
        "uuid-1",
        fixture.host
      ).count,
      1
    );
    assert.equal(
      fixture.requests.filter((path) => path === "/api/v1/video-channels/music/videos").length,
      1
    );
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});

test("crawlVideos skips a channel whose stored video count is zero", async () => {
  const temp = createTempDb("crawler-videos-single-pass-empty");
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ total: 0, data: [] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;

  try {
    seedChannel(temp.dbPath, host, 0);
    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: true,
      errorsOnly: false,
      newOnly: true,
      stopAfterFullPages: 2,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 0,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });

    assert.equal(requests, 0);
    assert.equal(
      getRow<{ count: number }>(
        temp.dbPath,
        "SELECT COUNT(*) AS count FROM video_crawl_progress WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        host
      ).count,
      0
    );
    assert.equal(getRow<{ count: number }>(temp.dbPath, "SELECT COUNT(*) AS count FROM videos").count, 0);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});

test("crawlVideos leaves an unknown-count channel for the count stage", async () => {
  const temp = createTempDb("crawler-videos-unknown-count");
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ total: 1, data: [] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;

  try {
    seedChannel(temp.dbPath, host, null);
    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: true,
      errorsOnly: false,
      newOnly: true,
      stopAfterFullPages: 2,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 0,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });

    assert.equal(requests, 0);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});

test("crawlVideos resumes an interrupted channel from its persisted page offset", async () => {
  const temp = createTempDb("crawler-videos-resume-offset");
  const starts: string[] = [];
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (url.pathname.includes("/api/v1/video-channels/")) {
      starts.push(url.searchParams.get("start") ?? "");
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ total: 51, data: [] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;

  try {
    seedChannel(temp.dbPath, host, 51);
    const store = new VideoStore({ dbPath: temp.dbPath });
    const channels = store.listChannelsWithVideos(1, [host]);
    store.prepareVideoProgress(channels, false);
    store.updateVideoProgress(host, "c1", "in_progress", 50, null);
    store.close();

    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: true,
      errorsOnly: false,
      newOnly: true,
      stopAfterFullPages: 2,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 0,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });

    assert.deepEqual(starts, ["50"]);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});

test("crawlVideos leaves legacy count errors for explicit retry mode", async () => {
  const temp = createTempDb("crawler-videos-legacy-count-error");
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ total: 1, data: [] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;

  try {
    seedChannel(temp.dbPath, host, null);
    const channels = new ChannelStore({ dbPath: temp.dbPath });
    channels.updateChannelVideosCountError("c1", host, "[timeout] prior count failure");
    channels.close();

    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: true,
      errorsOnly: false,
      newOnly: true,
      stopAfterFullPages: 2,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 0,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });

    assert.equal(requests, 0);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});

test("crawlVideos does not mistake overlapping staging and prod IDs for a fully existing page", async () => {
  const temp = createTempDb("crawler-videos-overlap-page");
  const prod = createTempDb("crawler-videos-overlap-prod");
  const requests: string[] = [];
  const makeVideo = (uuid: string) => ({
    uuid,
    name: uuid,
    channel: { id: "c1", name: "music", displayName: "Music" }
  });
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    requests.push(`${url.pathname}?${url.searchParams.toString()}`);
    response.writeHead(200, { "content-type": "application/json" });
    if (url.pathname === "/api/v1/video-channels/music/videos") {
      const start = Number(url.searchParams.get("start") ?? 0);
      response.end(JSON.stringify({
        total: 51,
        data: start === 0 ? [makeVideo("existing"), makeVideo("new-first")] : [makeVideo("new-later")]
      }));
      return;
    }
    response.end(JSON.stringify({}));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;

  try {
    seedChannel(temp.dbPath, host, 51);
    new VideoStore({ dbPath: prod.dbPath }).close();
    execSql(
      temp.dbPath,
      "INSERT INTO videos(video_id, video_uuid, instance_domain, last_checked_at) VALUES (?, ?, ?, 0)",
      "existing",
      "existing",
      host
    );
    execSql(
      prod.dbPath,
      "INSERT INTO videos(video_id, video_uuid, instance_domain, last_checked_at) VALUES (?, ?, ?, 0)",
      "existing",
      "existing",
      host
    );

    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: prod.dbPath,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: true,
      errorsOnly: false,
      newOnly: true,
      stopAfterFullPages: 1,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 0,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });

    assert.equal(
      getRow<{ count: number }>(
        temp.dbPath,
        "SELECT COUNT(*) AS count FROM videos WHERE video_id = ?",
        "new-later"
      ).count,
      1
    );
    assert.ok(requests.some((request) => request.includes("start=50")));
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
    prod.cleanup();
  }
});

test("crawlVideos prefers live detail media over stale list media during normal crawl", async () => {
  const temp = createTempDb("crawler-videos-live-media");
  const fixture = await startPeerTubeFixtureServer();

  try {
    seedChannel(temp.dbPath, fixture.host);

    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 2000,
      maxRetries: 1,
      resume: false,
      errorsOnly: false,
      newOnly: false,
      stopAfterFullPages: 0,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 0,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });

    const row = getRow<{ thumbnail_url: string; preview_path: string }>(
      temp.dbPath,
      "SELECT thumbnail_url, preview_path FROM videos WHERE video_id = ? AND instance_domain = ?",
      "uuid-1",
      fixture.host
    );

    assert.deepEqual(row, {
      thumbnail_url: `http://${fixture.host}/lazy-static/thumbnails/fresh.jpg`,
      preview_path: "/lazy-static/previews/fresh.jpg"
    });
    assert.ok(fixture.requests.includes("/api/v1/videos/uuid-1"));
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});

test("crawlVideos limits simultaneous requests to one PeerTube host", async () => {
  const temp = createTempDb("crawler-videos-host-limit");
  let activeRequests = 0;
  let maxActiveRequests = 0;
  const server = http.createServer((request, response) => {
    activeRequests += 1;
    maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    setTimeout(() => {
      if (url.pathname.includes("/api/v1/video-channels/")) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ total: 0, data: [] }));
      } else {
        response.writeHead(404, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: "not found" }));
      }
      activeRequests -= 1;
    }, 40);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;
  const channels = new ChannelStore({ dbPath: temp.dbPath });
  channels.markInstanceDone(host);
  channels.upsertChannels(["one", "two"].map((name, index) => ({
    channelId: `c${index + 1}`,
    channelName: name,
    channelUrl: `http://${host}/video-channels/${name}`,
    displayName: name,
    instanceDomain: host,
    videosCount: 1,
    followersCount: 0,
    avatarUrl: null
  })));
  channels.close();

  try {
    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 1,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: false,
      errorsOnly: false,
      newOnly: false,
      stopAfterFullPages: 0,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 1,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 0
    });
    assert.equal(maxActiveRequests, 1);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});

test("crawlVideos spaces normal crawl requests to one PeerTube host", async () => {
  const temp = createTempDb("crawler-videos-host-delay");
  const requestStartedAt: number[] = [];
  const server = http.createServer((_request, response) => {
    requestStartedAt.push(Date.now());
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ total: 0, data: [] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;
  const channels = new ChannelStore({ dbPath: temp.dbPath });
  channels.markInstanceDone(host);
  channels.upsertChannels(["one", "two"].map((name, index) => ({
    channelId: `c${index + 1}`,
    channelName: name,
    channelUrl: `http://${host}/video-channels/${name}`,
    displayName: name,
    instanceDomain: host,
    videosCount: 1,
    followersCount: 0,
    avatarUrl: null
  })));
  channels.close();

  try {
    await crawlVideos({
      dbPath: temp.dbPath,
      hostsFile: null,
      excludeHostsFile: null,
      existingDbPath: null,
      concurrency: 1,
      hostConcurrency: 2,
      timeoutMs: 1000,
      maxRetries: 0,
      resume: false,
      errorsOnly: false,
      newOnly: false,
      stopAfterFullPages: 0,
      sort: "-publishedAt",
      maxInstances: 0,
      maxChannels: 0,
      maxVideosPages: 1,
      tagsOnly: false,
      updateTags: false,
      commentsOnly: false,
      refreshThumbnails: false,
      hostDelayMs: 60
    });

    assert.equal(requestStartedAt.length, 2);
    assert.ok(
      requestStartedAt[1] - requestStartedAt[0] >= 45,
      `requests started only ${requestStartedAt[1] - requestStartedAt[0]}ms apart`
    );
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    temp.cleanup();
  }
});
