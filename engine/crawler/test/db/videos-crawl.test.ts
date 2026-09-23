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
import { crawlVideos } from "../../src/videos-worker.js";
import { createTempDb, getRow } from "./helpers.js";

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
function seedChannel(dbPath: string, host: string) {
  const channels = new ChannelStore({ dbPath });
  channels.markInstanceDone(host);
  channels.upsertChannels([
    {
      channelId: "c1",
      channelName: "music",
      channelUrl: `http://${host}/video-channels/music`,
      displayName: "Music",
      instanceDomain: host,
      videosCount: 1,
      followersCount: 10,
      avatarUrl: null
    }
  ]);
  channels.close();
}

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
