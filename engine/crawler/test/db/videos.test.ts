/**
 * Characterization tests for video crawler database persistence.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ChannelStore, VideoStore, type VideoChannelRow, type VideoUpsertRow } from "../../src/db.js";
import { allRows, createTempDb, getRow } from "./helpers.js";

const video: VideoUpsertRow = {
  videoId: "v1",
  videoUuid: "uuid-1",
  videoNumericId: 1,
  instanceDomain: "example.org",
  channelId: "c1",
  channelName: "music",
  channelUrl: "https://example.org/video-channels/music",
  accountName: "music@example.org",
  accountUrl: "https://example.org/accounts/music",
  title: "Song",
  description: "A song",
  tagsJson: null,
  category: "Music",
  publishedAt: 1,
  videoUrl: "https://example.org/w/uuid-1",
  duration: 60,
  thumbnailUrl: "https://example.org/thumb.jpg",
  embedPath: "/videos/embed/uuid-1",
  views: 10,
  likes: 2,
  dislikes: 0,
  commentsCount: null,
  nsfw: 0,
  previewPath: "/lazy-static/previews/uuid.jpg",
  lastCheckedAt: 100
};

function seedChannel(dbPath: string) {
  const channels = new ChannelStore({ dbPath });
  channels.upsertChannels([
    {
      channelId: "c1",
      channelName: "music",
      channelUrl: "https://example.org/video-channels/music",
      displayName: "Music",
      instanceDomain: "example.org",
      videosCount: 5,
      followersCount: 10,
      avatarUrl: null
    },
    {
      channelId: "c2",
      channelName: null,
      channelUrl: null,
      displayName: null,
      instanceDomain: "example.org",
      videosCount: 5,
      followersCount: 0,
      avatarUrl: null
    }
  ]);
  channels.close();
}

test("VideoStore state and channel listing preserve current behavior", () => {
  const temp = createTempDb("crawler-videos-state");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.setState("cursor", "abc");
    store.incrementState("count", 2);
    assert.equal(store.getState("cursor"), "abc");
    assert.equal(store.getState("count"), "2");
    assert.deepEqual(store.listInstances(), ["example.org"]);
    assert.deepEqual(store.listChannelsWithVideos(1, ["example.org"]), [
      {
        channel_id: "c1",
        channel_name: "music",
        display_name: "Music",
        channel_url: "https://example.org/video-channels/music",
        instance_domain: "example.org",
        videos_count: 5
      }
    ]);
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("VideoStore prepares progress, prunes missing channels, and returns work items", () => {
  const temp = createTempDb("crawler-videos-progress");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    const channels: VideoChannelRow[] = store.listChannelsWithVideos(1, ["example.org"]);
    store.prepareVideoProgress(channels, false);
    assert.deepEqual(store.listVideoWorkItems(["pending"]), [
      {
        instanceDomain: "example.org",
        channelId: "c1",
        channelName: "music",
        status: "pending",
        lastStart: 0,
        lastError: null
      }
    ]);
    store.updateVideoProgress("example.org", "c1", "error", 123, "boom");
    assert.deepEqual(
      getRow<{ status: string; last_start: number; last_error: string }>(
        temp.dbPath,
        "SELECT status, last_start, last_error FROM video_crawl_progress WHERE instance_domain = ? AND channel_id = ?",
        "example.org",
        "c1"
      ),
      { status: "error", last_start: 123, last_error: "boom" }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("VideoStore upserts videos and preserves tag/comment/error update effects", () => {
  const temp = createTempDb("crawler-videos-updates");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.upsertVideos([video]);
    store.upsertVideos([{ ...video, title: "Updated song", views: 20 }]);
    assert.equal(
      allRows(temp.dbPath, "SELECT * FROM videos WHERE video_id = ?", "v1").length,
      1
    );
    assert.deepEqual(
      getRow<{ title: string; views: number }>(
        temp.dbPath,
        "SELECT title, views FROM videos WHERE video_id = ? AND instance_domain = ?",
        "v1",
        "example.org"
      ),
      { title: "Updated song", views: 20 }
    );

    store.updateVideoError("v1", "example.org", "timeout");
    assert.equal(
      getRow<{ error_count: number; last_error: string }>(
        temp.dbPath,
        "SELECT error_count, last_error FROM videos WHERE video_id = ? AND instance_domain = ?",
        "v1",
        "example.org"
      ).error_count,
      1
    );

    store.updateVideoTags("v1", "example.org", "[\"music\"]");
    assert.deepEqual(
      getRow<{ tags_json: string; last_error: string | null; error_count: number }>(
        temp.dbPath,
        "SELECT tags_json, last_error, error_count FROM videos WHERE video_id = ? AND instance_domain = ?",
        "v1",
        "example.org"
      ),
      { tags_json: "[\"music\"]", last_error: null, error_count: 0 }
    );

    store.updateVideoComments("v1", "example.org", 7);
    assert.equal(
      getRow<{ comments_count: number; error_count: number }>(
        temp.dbPath,
        "SELECT comments_count, error_count FROM videos WHERE video_id = ? AND instance_domain = ?",
        "v1",
        "example.org"
      ).comments_count,
      7
    );

    store.updateVideoInvalid("v1", "example.org", "not-public");
    assert.deepEqual(
      getRow<{ invalid_reason: string; last_error: string; error_count: number }>(
        temp.dbPath,
        "SELECT invalid_reason, last_error, error_count FROM videos WHERE video_id = ? AND instance_domain = ?",
        "v1",
        "example.org"
      ),
      { invalid_reason: "not-public", last_error: "not-public", error_count: 1 }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});
