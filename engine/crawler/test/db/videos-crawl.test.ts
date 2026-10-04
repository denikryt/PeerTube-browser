/**
 * Scenario tests for the end-to-end video crawl path.
 *
 * These tests run the real crawler worker against a tiny local HTTP server so
 * persisted video rows prove which PeerTube payload won during ingestion.
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import test from "node:test";
import Database from "better-sqlite3";

import { ChannelStore } from "../../src/db/channels.js";
import { VideoStore } from "../../src/db/videos.js";
import { crawlVideos, type VideoCrawlOptions } from "../../src/videos-worker.js";
import type { VideoUpsertRow } from "../../src/db/types.js";
import { createTempDb, execSql, getRow } from "./helpers.js";
import { NoNetworkError } from "../../src/http.js";

/**
 * Start a minimal PeerTube-like HTTP server for one crawl scenario.
 */
async function startPeerTubeFixtureServer(
  detailResponse: { status?: number; body?: object } = {
    body: {
      thumbnails: [
        { fileUrl: "/lazy-static/thumbnails/small.jpg", width: 280, height: 157 },
        { fileUrl: "/lazy-static/thumbnails/fresh.jpg", width: 850, height: 480 }
      ],
      previewPath: "/lazy-static/previews/fresh.jpg"
    }
  }
) {
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
              thumbnailPath: "/lazy-static/thumbnails/list.jpg",
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
      response.writeHead(detailResponse.status ?? 200, { "content-type": "application/json" });
      response.end(JSON.stringify(detailResponse.body ?? {}));
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

    const row = getRow<{ thumbnail_url: string; thumbnail_candidates_json: string; preview_path: string }>(
      temp.dbPath,
      "SELECT thumbnail_url, thumbnail_candidates_json, preview_path FROM videos WHERE video_id = ? AND instance_domain = ?",
      "uuid-1",
      fixture.host
    );

    assert.deepEqual(row, {
      thumbnail_url: `http://${fixture.host}/lazy-static/thumbnails/fresh.jpg`,
      thumbnail_candidates_json: JSON.stringify([
        { url: `http://${fixture.host}/lazy-static/thumbnails/fresh.jpg`, width: 850, height: 480 },
        { url: `http://${fixture.host}/lazy-static/thumbnails/small.jpg`, width: 280, height: 157 }
      ]),
      preview_path: "/lazy-static/previews/fresh.jpg"
    });
    assert.ok(fixture.requests.includes("/api/v1/videos/uuid-1"));
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});



test("normal crawl keeps SQL NULL for successful legacy detail without preview promotion", async () => {
  const temp = createTempDb("crawler-videos-legacy-thumbnail-shape");
  const fixture = await startPeerTubeFixtureServer({
    body: { thumbnailPath: "/legacy-detail.jpg", previewPath: "/legacy-preview.jpg" }
  });
  try {
    seedChannel(temp.dbPath, fixture.host);
    await crawlVideos(metadataOptions(temp.dbPath));

    assert.deepEqual(
      getRow<{ thumbnail_candidates_json: string | null; thumbnail_url: string; preview_path: string }>(
        temp.dbPath,
        "SELECT thumbnail_candidates_json, thumbnail_url, preview_path FROM videos WHERE video_id='uuid-1'"
      ),
      {
        thumbnail_candidates_json: null,
        thumbnail_url: `http://${fixture.host}/legacy-detail.jpg`,
        preview_path: "/legacy-preview.jpg"
      }
    );
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});

test("normal crawl detail failure keeps SQL NULL and list thumbnail but never uses preview", async () => {
  const temp = createTempDb("crawler-videos-thumbnail-detail-failure");
  const fixture = await startPeerTubeFixtureServer({ status: 500, body: { error: "boom" } });
  try {
    seedChannel(temp.dbPath, fixture.host);
    await crawlVideos(metadataOptions(temp.dbPath, { maxRetries: 0 }));

    assert.deepEqual(
      getRow<{ thumbnail_candidates_json: string | null; thumbnail_url: string; preview_path: string }>(
        temp.dbPath,
        "SELECT thumbnail_candidates_json, thumbnail_url, preview_path FROM videos WHERE video_id='uuid-1'"
      ),
      {
        thumbnail_candidates_json: null,
        thumbnail_url: `http://${fixture.host}/lazy-static/thumbnails/list.jpg`,
        preview_path: "/lazy-static/previews/stale.jpg"
      }
    );
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});

test("normal crawl authoritative empty thumbnails clear the singular compatibility mirror", async () => {
  const temp = createTempDb("crawler-videos-empty-thumbnail-array");
  const fixture = await startPeerTubeFixtureServer({
    body: { thumbnails: [], thumbnailPath: "/legacy-detail.jpg", previewPath: "/preview.jpg" }
  });
  try {
    seedChannel(temp.dbPath, fixture.host);
    await crawlVideos(metadataOptions(temp.dbPath));

    assert.deepEqual(
      getRow<{ thumbnail_candidates_json: string; thumbnail_url: string | null }>(
        temp.dbPath,
        "SELECT thumbnail_candidates_json, thumbnail_url FROM videos WHERE video_id='uuid-1'"
      ),
      { thumbnail_candidates_json: "[]", thumbnail_url: null }
    );
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


// Metadata-v1 crawl scenarios from the ActivityPub parity milestone.
function metadataOptions(dbPath: string, overrides: Partial<VideoCrawlOptions> = {}): VideoCrawlOptions {
  return {
    dbPath,
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
    maxVideosPages: 0,
    tagsOnly: false,
    updateTags: false,
    commentsOnly: false,
    refreshThumbnails: false,
    hostDelayMs: 0,
    ...overrides
  };
}

function seedMetadataChannel(dbPath: string, host: string) {
  const channels = new ChannelStore({ dbPath });
  channels.markInstanceDone(host);
  channels.upsertChannels([{
    channelId: "c1",
    channelName: "music",
    channelUrl: `http://${host}/video-channels/music`,
    displayName: "Music",
    instanceDomain: host,
    videosCount: 1,
    followersCount: 1,
    avatarUrl: null
  }]);
  channels.close();
}

async function metadataFixture(handler: (url: URL) => object) {
  let requests = 0;
  const server = http.createServer((request, response) => {
    requests += 1;
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(handler(url)));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return {
    host: `127.0.0.1:${address.port}`,
    requestCount: () => requests,
    close: () => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  };
}

test("ordinary repeated crawl protects embedding inputs while refreshing safe metadata", async () => {
  const temp = createTempDb("crawler-repeat-safe-refresh");
  const remote = await metadataFixture((url) => {
    if (url.pathname === "/api/v1/video-channels/music/videos") {
      return { total: 1, data: [{
        id: 1, uuid: "uuid-1", name: "Remote title", description: "Remote description",
        url: `http://${remote.host}/w/uuid-1`, category: { id: "15", label: "Gaming" },
        channel: { id: "c1", name: "music", displayName: "Renamed Music", url: `http://${remote.host}/video-channels/music` },
        views: 20
      }] };
    }
    if (url.pathname === "/api/v1/videos/uuid-1") {
      return {
        id: 1, uuid: "uuid-1", name: "Detail title", description: "Detail description",
        url: `http://${remote.host}/w/uuid-1`, tags: ["new"], category: { id: "15", label: "Gaming" },
        language: { id: "en", label: "English" }, licence: { id: "1", label: "Attribution" },
        channel: { id: "c1", name: "music", displayName: "Renamed Music", url: `http://${remote.host}/video-channels/music` },
        account: { name: "alice", displayName: "Alice", url: `http://${remote.host}/accounts/alice` },
        thumbnails: [{ fileUrl: "/thumb.jpg", width: 640, height: 360 }], views: 25, comments: 9,
        isLive: false
      };
    }
    return {};
  });
  try {
    seedMetadataChannel(temp.dbPath, remote.host);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([{
      videoId: "uuid-1", videoUuid: "uuid-1", videoNumericId: 1, instanceDomain: remote.host,
      channelId: "c1", channelName: "Music", channelUrl: `http://${remote.host}/video-channels/music`,
      accountName: "Old Alice", accountUrl: null, title: "Stored title", description: "Stored description",
      tagsJson: '["old"]', category: "Music", categoryId: null, publishedAt: 1,
      videoUrl: null, duration: 60, thumbnailUrl: null, thumbnailCandidatesJson: null, embedPath: null,
      views: 1, likes: 0, dislikes: 0, commentsCount: 1, nsfw: 0,
      previewPath: null, lastCheckedAt: 1, metadataVersion: 0
    }]);
    store.close();

    await crawlVideos(metadataOptions(temp.dbPath));

    assert.deepEqual(
      getRow<{
        title: string; description: string; tags_json: string; category: string;
        channel_name: string; category_id: string | null; language: string;
        views: number; comments_count: number; thumbnail_url: string;
        thumbnail_width: number; thumbnail_height: number; video_url: string;
        channel_url: string; account_url: string; metadata_version: number;
      }>(temp.dbPath, `SELECT title, description, tags_json, category, channel_name,
        category_id, language, views, comments_count, thumbnail_url, thumbnail_width,
        thumbnail_height, video_url, channel_url, account_url, metadata_version
        FROM videos WHERE video_id='uuid-1'`),
      {
        title: "Stored title", description: "Stored description", tags_json: '["old"]',
        category: "Music", channel_name: "Music", category_id: null, language: "en",
        views: 25, comments_count: 9, thumbnail_url: `http://${remote.host}/thumb.jpg`,
        thumbnail_width: 640, thumbnail_height: 360, video_url: `http://${remote.host}/w/uuid-1`,
        channel_url: `http://${remote.host}/video-channels/music`, account_url: `http://${remote.host}/accounts/alice`,
        metadata_version: 1
      }
    );
    assert.equal(
      getRow<{ count: number }>(temp.dbPath, "SELECT COUNT(*) AS count FROM videos").count,
      1
    );
  } finally {
    await remote.close();
    temp.cleanup();
  }
});

test("fresh crawl persists detail tags and protocol identity URLs", async () => {
  const temp = createTempDb("crawler-fresh-metadata");
  const remote = await metadataFixture((url) => {
    if (url.pathname === "/api/v1/video-channels/music/videos") {
      return { total: 1, data: [{ uuid: "uuid-1", name: "List", channel: { id: "c1", name: "music" } }] };
    }
    return {
      id: 1, uuid: "uuid-1", name: "Detail", tags: ["linux", "foss"],
      url: `http://${remote.host}/w/uuid-1`, language: { id: "uk", label: "Українська" },
      category: { id: "3", label: "Education" },
      channel: { id: "c1", name: "music", displayName: "Music", url: `http://${remote.host}/video-channels/music` },
      account: { name: "alice", displayName: "Alice Author", url: `http://${remote.host}/accounts/alice` },
      isLive: false
    };
  });
  try {
    seedMetadataChannel(temp.dbPath, remote.host);
    await crawlVideos(metadataOptions(temp.dbPath));
    assert.deepEqual(
      getRow<{ tags_json: string; language: string; video_url: string; channel_url: string; account_url: string; account_name: string; account_username: string }>(
        temp.dbPath,
        "SELECT tags_json, language, video_url, channel_url, account_url, account_name, account_username FROM videos WHERE video_id='uuid-1'"
      ),
      {
        tags_json: '["linux","foss"]', language: "uk",
        video_url: `http://${remote.host}/w/uuid-1`, channel_url: `http://${remote.host}/video-channels/music`,
        account_url: `http://${remote.host}/accounts/alice`, account_name: "Alice Author", account_username: "alice"
      }
    );
  } finally {
    await remote.close();
    temp.cleanup();
  }
});

test("metadata mode rejects stale schema before any HTTP request or schema mutation", async () => {
  const temp = createTempDb("crawler-metadata-stale-worker");
  const remote = await metadataFixture(() => ({}));
  try {
    const db = new Database(temp.dbPath);
    db.exec(`
      CREATE TABLE videos(video_id TEXT NOT NULL, video_uuid TEXT, instance_domain TEXT NOT NULL,
        PRIMARY KEY(video_id, instance_domain));
      CREATE TABLE channels(channel_id TEXT NOT NULL, instance_domain TEXT NOT NULL,
        PRIMARY KEY(channel_id, instance_domain));
      INSERT INTO videos VALUES ('v1', 'uuid-1', '${remote.host}');
    `);
    const before = db.pragma("schema_version", { simple: true });
    db.close();

    await assert.rejects(
      crawlVideos(metadataOptions(temp.dbPath, { metadataOnly: true })),
      /migrate-whitelist\.py/
    );
    assert.equal(remote.requestCount(), 0);
    const after = new Database(temp.dbPath, { readonly: true });
    assert.equal(after.pragma("schema_version", { simple: true }), before);
    after.close();
  } finally {
    await remote.close();
    temp.cleanup();
  }
});

test("metadata mode updates migrated DB without schema mutation", async () => {
  const temp = createTempDb("crawler-metadata-current-worker");
  const remote = await metadataFixture((_url) => ({
    id: 1, uuid: "uuid-1", name: "Current", language: { id: "en", label: "English" },
    category: { id: "3", label: "Music" }, isLive: false,
    channel: { id: "c1", name: "music", displayName: "Music", url: `http://${remote.host}/video-channels/music` },
    account: { name: "alice", displayName: "Alice", url: `http://${remote.host}/accounts/alice` }
  }));
  try {
    seedMetadataChannel(temp.dbPath, remote.host);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([{
      videoId: "v1", videoUuid: "uuid-1", videoNumericId: 1, instanceDomain: remote.host,
      channelId: "c1", channelName: "Music", channelUrl: `http://${remote.host}/video-channels/music`,
      accountName: null, accountUrl: null, title: "Current", description: null, tagsJson: null,
      category: "Music", publishedAt: null, videoUrl: null, duration: null, thumbnailUrl: null,
      thumbnailCandidatesJson: null, embedPath: null, views: null, likes: null, dislikes: null, commentsCount: null, nsfw: 0,
      previewPath: null, lastCheckedAt: 1, metadataVersion: 0
    }]);
    store.close();
    const db = new Database(temp.dbPath, { readonly: true });
    const before = db.pragma("schema_version", { simple: true });
    db.close();

    const lines: string[] = [];
    const originalLog = console.log;
    console.log = (...values: unknown[]) => lines.push(values.join(" "));
    try {
      await crawlVideos(metadataOptions(temp.dbPath, { metadataOnly: true }));
    } finally {
      console.log = originalLog;
    }

    const after = new Database(temp.dbPath, { readonly: true });
    assert.equal(after.pragma("schema_version", { simple: true }), before);
    after.close();
    assert.deepEqual(
      getRow<{ language: string; metadata_version: number }>(
        temp.dbPath, "SELECT language, metadata_version FROM videos WHERE video_id='v1'"
      ),
      { language: "en", metadata_version: 1 }
    );
    assert.ok(lines.includes("[metadata] instances=1 videos=1 concurrency=1 update=false healthy_only=false"));
    assert.ok(lines.includes("[metadata] video=1/1 updated=1 errors=0 done " + remote.host + "/v1"));
  } finally {
    await remote.close();
    temp.cleanup();
  }
});

/** Seed one existing video for dedicated thumbnail-maintenance scenarios. */
function seedThumbnailVideo(
  dbPath: string,
  host: string,
  overrides: Partial<VideoUpsertRow> = {}
) {
  const store = new VideoStore({ dbPath });
  store.insertNewVideos([{
    videoId: "v1",
    videoUuid: "uuid-1",
    videoNumericId: 1,
    instanceDomain: host,
    channelId: null,
    channelName: null,
    channelUrl: null,
    accountName: null,
    accountUrl: null,
    title: "Video",
    description: null,
    tagsJson: null,
    category: null,
    publishedAt: null,
    videoUrl: null,
    duration: null,
    thumbnailUrl: `http://${host}/legacy-old.jpg`,
    thumbnailCandidatesJson: null,
    embedPath: null,
    views: null,
    likes: null,
    dislikes: null,
    commentsCount: null,
    nsfw: 0,
    previewPath: "/preview-only.jpg",
    lastCheckedAt: 1,
    ...overrides
  }]);
  store.close();
}

for (const mode of ["tagsOnly", "commentsOnly", "metadataOnly", "refreshThumbnails"] as const) {
  for (const observation of ["ok", "404", "410", "403", "429", "500", "tls", "cert", "timeout", "json", "no-network"] as const) {
    test(`${mode} detail ${observation} persists only canonical absence`, async () => {
      const temp = createTempDb(`canonical_absence_v1-${mode}-${observation}`);
      const originalFetch = globalThis.fetch;
      try {
        seedThumbnailVideo(temp.dbPath, "example.org");
        // Only the PeerTube transport edge is replaced; real workers and stores
        // decide whether this observation affects canonical availability.
        globalThis.fetch = async () => {
          if (["tls", "cert", "timeout"].includes(observation)) {
            throw new Error(observation === "tls" ? "TLS handshake failed" : observation === "cert" ? "certificate has expired" : "timeout");
          }
          const status = /^\d+$/.test(observation) ? Number(observation) : 200;
          const response = new Response(JSON.stringify({ id: 1, uuid: "uuid-1", name: "Video", tags: ["linux"], comments: 2, thumbnails: [] }), { status });
          if (observation === "json" || observation === "no-network") {
            response.json = async () => { throw observation === "json" ? new SyntaxError("invalid JSON") : new NoNetworkError("offline"); };
          }
          return response;
        };
        const action = crawlVideos(metadataOptions(temp.dbPath, { [mode]: true, maxRetries: 0 }));
        // Tags/comments preserve process-level abort. Newer projection workers
        // keep their existing handling rather than acquiring a new abort policy.
        if (observation === "no-network" && (mode === "tagsOnly" || mode === "commentsOnly")) {
          await assert.rejects(action, NoNetworkError);
        } else {
          await action;
        }
        const row = getRow<{ invalid_reason: string | null; invalid_at: number | null; error_count: number }>(
          temp.dbPath, "SELECT invalid_reason,invalid_at,error_count FROM videos WHERE video_id='v1'"
        );
        const reason = observation === "404" ? "not_found" : observation === "410" ? "gone" : null;
        assert.equal(row.invalid_reason, reason);
        assert.equal(row.invalid_at !== null, reason !== null);
        if (observation === "no-network" && (mode === "tagsOnly" || mode === "commentsOnly")) assert.equal(row.error_count, 0);
        if (["404", "410", "403", "429", "500", "tls", "cert", "timeout", "json"].includes(observation)) assert.ok(row.error_count > 0);
      } finally {
        globalThis.fetch = originalFetch;
        temp.cleanup();
      }
    });
  }
}

/** Start one detail-only HTTP fixture and expose every requested path. */
async function thumbnailDetailFixture(
  responder: (url: URL) => { status?: number; body?: object }
) {
  const requests: string[] = [];
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    requests.push(url.pathname);
    const result = responder(url);
    response.writeHead(result.status ?? 200, { "content-type": "application/json" });
    response.end(JSON.stringify(result.body ?? {}));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return {
    host: `127.0.0.1:${address.port}`,
    requests,
    close: () => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  };
}

test("thumbnail maintenance persists ordered candidates without probing image URLs", async () => {
  const temp = createTempDb("crawler-thumbnail-modern-refresh");
  const remote = await thumbnailDetailFixture((url) => {
    assert.equal(url.pathname, "/api/v1/videos/uuid-1");
    return {
      body: {
        thumbnails: [
          { fileUrl: "/thumb-small.jpg", width: 280, height: 157 },
          { fileUrl: "/thumb-large.jpg", width: 850, height: 480 }
        ]
      }
    };
  });
  try {
    seedThumbnailVideo(temp.dbPath, remote.host);
    const lines: string[] = [];
    const originalLog = console.log;
    console.log = (...values: unknown[]) => lines.push(values.join(" "));
    try {
      await crawlVideos(metadataOptions(temp.dbPath, { refreshThumbnails: true, resume: true }));
    } finally {
      console.log = originalLog;
    }
    assert.deepEqual(
      getRow<{ thumbnail_candidates_json: string; thumbnail_url: string; thumbnail_width: number }>(
        temp.dbPath,
        "SELECT thumbnail_candidates_json, thumbnail_url, thumbnail_width FROM videos WHERE video_id='v1'"
      ),
      {
        thumbnail_candidates_json: JSON.stringify([
          { url: `http://${remote.host}/thumb-large.jpg`, width: 850, height: 480 },
          { url: `http://${remote.host}/thumb-small.jpg`, width: 280, height: 157 }
        ]),
        thumbnail_url: `http://${remote.host}/thumb-large.jpg`,
        thumbnail_width: 850
      }
    );
    assert.deepEqual(remote.requests, ["/api/v1/videos/uuid-1"]);
    assert.ok(lines.includes(
      `[thumbnails] video=1/1 updated=1 errors=0 candidates=2 ${remote.host}/uuid-1`
    ));
  } finally {
    await remote.close();
    temp.cleanup();
  }
});

test("thumbnail maintenance preserves legacy-shaped rows and generic video health", async () => {
  const temp = createTempDb("crawler-thumbnail-legacy-refresh");
  const remote = await thumbnailDetailFixture(() => ({ body: { thumbnailPath: "/legacy-new.jpg" } }));
  try {
    seedThumbnailVideo(temp.dbPath, remote.host);
    execSql(
      temp.dbPath,
      "UPDATE videos SET error_count=2, last_error='existing-error', last_error_at=123 WHERE video_id='v1'"
    );
    await crawlVideos(metadataOptions(temp.dbPath, { refreshThumbnails: true, resume: true }));
    await crawlVideos(metadataOptions(temp.dbPath, { refreshThumbnails: true, resume: true }));
    assert.equal(remote.requests.length, 2);
    assert.deepEqual(
      getRow<{ thumbnail_candidates_json: string | null; thumbnail_url: string; error_count: number; last_error: string; last_error_at: number }>(
        temp.dbPath,
        "SELECT thumbnail_candidates_json, thumbnail_url, error_count, last_error, last_error_at FROM videos WHERE video_id='v1'"
      ),
      {
        thumbnail_candidates_json: null,
        thumbnail_url: `http://${remote.host}/legacy-old.jpg`,
        error_count: 2,
        last_error: "existing-error",
        last_error_at: 123
      }
    );
  } finally {
    await remote.close();
    temp.cleanup();
  }
});

test("thumbnail detail failure preserves SQL-NULL resume state and records generic health", async () => {
  const temp = createTempDb("crawler-thumbnail-failed-refresh");
  const remote = await thumbnailDetailFixture(() => ({ status: 500, body: { error: "boom" } }));
  try {
    seedThumbnailVideo(temp.dbPath, remote.host);
    execSql(
      temp.dbPath,
      "UPDATE videos SET error_count=2, last_error='existing-error', last_error_at=123 WHERE video_id='v1'"
    );
    await crawlVideos(metadataOptions(temp.dbPath, {
      refreshThumbnails: true,
      resume: true,
      maxRetries: 0,
      timeoutMs: 500
    }));
    const row = getRow<{ thumbnail_candidates_json: string | null; thumbnail_url: string; error_count: number; last_error: string; last_error_at: number }>(
      temp.dbPath,
      "SELECT thumbnail_candidates_json, thumbnail_url, error_count, last_error, last_error_at FROM videos WHERE video_id='v1'"
    );
    assert.equal(row.thumbnail_candidates_json, null);
    assert.equal(row.thumbnail_url, `http://${remote.host}/legacy-old.jpg`);
    assert.equal(row.error_count, 3);
    assert.match(row.last_error, /HTTP 500/);
    assert.notEqual(row.last_error_at, 123);
  } finally {
    await remote.close();
    temp.cleanup();
  }
});

/** Start a mutable thumbnail detail fixture for cross-host resume tests. */
async function mutableThumbnailDetailFixture() {
  let mode: "modern" | "legacy" | "failure" = "modern";
  const requests: string[] = [];
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    requests.push(url.pathname);
    if (mode === "failure") {
      response.writeHead(500, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "boom" }));
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(
      mode === "legacy"
        ? { thumbnailPath: "/legacy.jpg" }
        : { thumbnails: [{ fileUrl: "/modern.jpg", width: 850, height: 480 }] }
    ));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return {
    host: `127.0.0.1:${address.port}`,
    requests,
    setMode(next: "modern" | "legacy" | "failure") { mode = next; },
    close: () => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  };
}

/** Seed one uniquely identified thumbnail row on a chosen host. */
function seedThumbnailRow(dbPath: string, host: string, videoId: string, videoUuid: string) {
  seedThumbnailVideo(dbPath, host, { videoId, videoUuid });
}

test("thumbnail max-instances alone cannot advance past a persistently legacy first host", async () => {
  const temp = createTempDb("crawler-thumbnail-resume-legacy-starvation");
  const firstFixture = await mutableThumbnailDetailFixture();
  const secondFixture = await mutableThumbnailDetailFixture();
  const fixtures = [firstFixture, secondFixture].sort((left, right) => left.host.localeCompare(right.host));
  fixtures[0].setMode("legacy");
  fixtures[1].setMode("modern");
  try {
    seedThumbnailRow(temp.dbPath, fixtures[0].host, "v-a", "uuid-a");
    seedThumbnailRow(temp.dbPath, fixtures[1].host, "v-b", "uuid-b");

    const options = metadataOptions(temp.dbPath, {
      refreshThumbnails: true,
      resume: true,
      maxInstances: 1
    });
    await crawlVideos(options);
    await crawlVideos(options);

    assert.equal(fixtures[0].requests.length, 2);
    assert.equal(fixtures[1].requests.length, 0);
    for (const id of ["v-a", "v-b"]) {
      assert.equal(
        getRow<{ value: string | null }>(temp.dbPath, `SELECT thumbnail_candidates_json AS value FROM videos WHERE video_id='${id}'`).value,
        null
      );
    }
  } finally {
    await Promise.all([firstFixture.close(), secondFixture.close()]);
    temp.cleanup();
  }
});

test("thumbnail max-instances alone does not skip a persistently failing first host", async () => {
  const temp = createTempDb("crawler-thumbnail-resume-starvation");
  const firstFixture = await mutableThumbnailDetailFixture();
  const secondFixture = await mutableThumbnailDetailFixture();
  const fixtures = [firstFixture, secondFixture].sort((left, right) => left.host.localeCompare(right.host));
  fixtures[0].setMode("failure");
  fixtures[1].setMode("modern");
  try {
    seedThumbnailRow(temp.dbPath, fixtures[0].host, "v-a", "uuid-a");
    seedThumbnailRow(temp.dbPath, fixtures[1].host, "v-b", "uuid-b");
    const options = metadataOptions(temp.dbPath, {
      refreshThumbnails: true,
      resume: true,
      maxInstances: 1,
      maxRetries: 0,
      timeoutMs: 500
    });

    await crawlVideos(options);

    // The maintenance batch must remain pinned to the first scoped host while
    // its rows stay resumable. Detail retrieval may legitimately make extra
    // protocol or retry attempts, so this regression protects progression
    // semantics rather than an implementation-specific request count.
    const requestsAfterFirstRun = fixtures[0].requests.length;
    assert.ok(requestsAfterFirstRun > 0);
    assert.equal(fixtures[1].requests.length, 0);

    await crawlVideos(options);

    assert.ok(fixtures[0].requests.length > requestsAfterFirstRun);
    assert.equal(fixtures[1].requests.length, 0);
    for (const id of ["v-a", "v-b"]) {
      assert.equal(
        getRow<{ value: string | null }>(temp.dbPath, `SELECT thumbnail_candidates_json AS value FROM videos WHERE video_id='${id}'`).value,
        null
      );
    }
  } finally {
    await Promise.all([firstFixture.close(), secondFixture.close()]);
    temp.cleanup();
  }
});

test("thumbnail hosts-file defines the explicit maintenance batch", async () => {
  const temp = createTempDb("crawler-thumbnail-host-batch");
  const firstFixture = await mutableThumbnailDetailFixture();
  const secondFixture = await mutableThumbnailDetailFixture();
  try {
    seedThumbnailRow(temp.dbPath, firstFixture.host, "v-a", "uuid-a");
    seedThumbnailRow(temp.dbPath, secondFixture.host, "v-b", "uuid-b");
    const hostsFile = `${temp.dir}/thumbnail-batch.txt`;
    fs.writeFileSync(hostsFile, `${secondFixture.host}\n`, "utf8");

    await crawlVideos(metadataOptions(temp.dbPath, {
      refreshThumbnails: true,
      resume: true,
      hostsFile
    }));

    assert.equal(firstFixture.requests.length, 0);
    assert.equal(secondFixture.requests.length, 1);
    assert.equal(
      getRow<{ value: string | null }>(temp.dbPath, "SELECT thumbnail_candidates_json AS value FROM videos WHERE video_id='v-a'").value,
      null
    );
    assert.equal(
      getRow<{ value: string }>(temp.dbPath, "SELECT thumbnail_candidates_json AS value FROM videos WHERE video_id='v-b'").value,
      JSON.stringify([{ url: `http://${secondFixture.host}/modern.jpg`, width: 850, height: 480 }])
    );
  } finally {
    await Promise.all([firstFixture.close(), secondFixture.close()]);
    temp.cleanup();
  }
});

test("thumbnail maintenance only-healthy-hosts excludes error and unknown instances", async () => {
  const temp = createTempDb("crawler-thumbnail-healthy-hosts");
  const healthyFixture = await mutableThumbnailDetailFixture();
  const errorFixture = await mutableThumbnailDetailFixture();
  const unknownFixture = await mutableThumbnailDetailFixture();
  try {
    seedThumbnailRow(temp.dbPath, healthyFixture.host, "healthy", "uuid-healthy");
    seedThumbnailRow(temp.dbPath, errorFixture.host, "error", "uuid-error");
    seedThumbnailRow(temp.dbPath, unknownFixture.host, "unknown", "uuid-unknown");
    // Health is intentionally persisted before scheduling so this proves the
    // thumbnail path uses the same `health_status = ok` contract as metadata.
    execSql(temp.dbPath, `INSERT INTO instances(host, health_status) VALUES ('${healthyFixture.host}', 'ok')`);
    execSql(temp.dbPath, `INSERT INTO instances(host, health_status) VALUES ('${errorFixture.host}', 'error')`);

    await crawlVideos(metadataOptions(temp.dbPath, { refreshThumbnails: true, onlyHealthyHosts: true }));

    assert.equal(healthyFixture.requests.length, 1);
    assert.equal(errorFixture.requests.length, 0);
    assert.equal(unknownFixture.requests.length, 0);
    assert.notEqual(getRow<{ value: string | null }>(temp.dbPath, "SELECT thumbnail_candidates_json AS value FROM videos WHERE video_id='healthy'").value, null);
    assert.equal(getRow<{ value: string | null }>(temp.dbPath, "SELECT thumbnail_candidates_json AS value FROM videos WHERE video_id='error'").value, null);
    assert.equal(getRow<{ value: string | null }>(temp.dbPath, "SELECT thumbnail_candidates_json AS value FROM videos WHERE video_id='unknown'").value, null);
  } finally {
    await Promise.all([healthyFixture.close(), errorFixture.close(), unknownFixture.close()]);
    temp.cleanup();
  }
});
