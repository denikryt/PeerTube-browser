/**
 * Characterization tests for video crawler database persistence.
 */

import assert from "node:assert/strict";
import test from "node:test";
import Database from "better-sqlite3";

import { ChannelStore } from "../../src/db/channels.js";
import type {
  ExistingVideoRefresh,
  VideoChannelRow,
  VideoDetailMetadataPatch,
  VideoUpsertRow
} from "../../src/db/types.js";
import { VideoStore } from "../../src/db/videos.js";
import { assertMetadataMaintenanceSchema } from "../../src/db/schema.js";
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
  channels.markInstanceDone("example.org");
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

test("VideoStore scoped resume preserves another host's completed progress", () => {
  const temp = createTempDb("crawler-videos-scoped-progress");
  try {
    const channels = new ChannelStore({ dbPath: temp.dbPath });
    channels.markInstanceDone("a.example");
    channels.markInstanceDone("b.example");
    channels.upsertChannels([
      {
        channelId: "a1", channelName: "a", channelUrl: null, displayName: "A",
        instanceDomain: "a.example", videosCount: 1, followersCount: 0, avatarUrl: null
      },
      {
        channelId: "b1", channelName: "b", channelUrl: null, displayName: "B",
        instanceDomain: "b.example", videosCount: 1, followersCount: 0, avatarUrl: null
      }
    ]);
    channels.close();

    const store = new VideoStore({ dbPath: temp.dbPath });
    const allChannels = store.listChannelsWithVideos(1, ["a.example", "b.example"]);
    store.prepareVideoProgress(allChannels, false);
    store.updateVideoProgress("a.example", "a1", "done", 0, null);

    const bChannels = store.listChannelsWithVideos(1, ["b.example"]);
    store.prepareVideoProgress(bChannels, true, ["b.example"]);

    assert.equal(store.listVideoWorkItems(["done"], ["a.example"]).length, 1);
    assert.equal(store.listVideoWorkItems(["pending"], ["b.example"]).length, 1);
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("VideoStore uses explicit insert/refresh semantics and preserves maintenance updates", () => {
  const temp = createTempDb("crawler-videos-updates");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([video]);
    store.refreshExistingVideoMetadata([{ base: { ...video, title: "Updated song", views: 20 } }]);
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
      { title: "Song", views: 20 }
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

test("VideoStore refreshes thumbnail URLs without touching other crawl state", () => {
  const temp = createTempDb("crawler-videos-thumbnails");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([video]);

    assert.deepEqual(store.listVideosForThumbnailRefresh(), [
      {
        videoId: "v1",
        videoUuid: "uuid-1",
        instanceDomain: "example.org"
      }
    ]);

    store.updateVideoThumbnail("v1", "example.org", "https://example.org/new-thumb.jpg", 200);
    assert.deepEqual(
      getRow<{ thumbnail_url: string; last_checked_at: number }>(
        temp.dbPath,
        "SELECT thumbnail_url, last_checked_at FROM videos WHERE video_id = ? AND instance_domain = ?",
        "v1",
        "example.org"
      ),
      {
        thumbnail_url: "https://example.org/new-thumb.jpg",
        last_checked_at: 200
      }
    );

    store.close();
  } finally {
    temp.cleanup();
  }
});


// Metadata-v1 persistence regressions from the ActivityPub parity milestone.
function metadataRow(overrides: Partial<VideoUpsertRow> = {}): VideoUpsertRow {
  return {
    videoId: "v1",
    videoUuid: "uuid-1",
    videoNumericId: 1,
    instanceDomain: "example.org",
    channelId: "c1",
    channelName: "Music",
    channelUrl: "https://example.org/video-channels/music",
    accountName: "Alice Display",
    accountUrl: "https://example.org/accounts/alice",
    title: "Old title",
    description: "Old description",
    tagsJson: '["old"]',
    category: "Music",
    categoryId: null,
    licenceId: null,
    licence: null,
    language: null,
    languageLabel: null,
    publishedAt: 1,
    originallyPublishedAt: null,
    updatedAt: null,
    videoUrl: "https://example.org/w/uuid-1",
    duration: 60,
    thumbnailUrl: "https://example.org/old.jpg",
    thumbnailWidth: null,
    thumbnailHeight: null,
    embedPath: "/videos/embed/uuid-1",
    views: 10,
    likes: 2,
    dislikes: 0,
    commentsCount: 3,
    nsfw: 0,
    sensitiveSummary: null,
    isLive: 0,
    permanentLive: null,
    liveSaveReplay: null,
    aspectRatio: null,
    support: null,
    accountUsername: "alice",
    accountAvatarUrl: null,
    metadataVersion: 0,
    previewPath: "/preview-old.jpg",
    lastCheckedAt: 100,
    ...overrides
  };
}

/** Build the successful-detail patch used by persistence-focused tests. */
function metadataDetailPatch(row: VideoUpsertRow): VideoDetailMetadataPatch {
  return {
    categoryId: row.categoryId ?? null,
    category: row.category,
    licenceId: row.licenceId ?? null,
    licence: row.licence ?? null,
    language: row.language ?? null,
    languageLabel: row.languageLabel ?? null,
    sensitiveSummary: row.sensitiveSummary ?? null,
    originallyPublishedAt: row.originallyPublishedAt ?? null,
    updatedAt: row.updatedAt ?? null,
    aspectRatio: row.aspectRatio ?? null,
    support: row.support ?? null,
    accountUsername: row.accountUsername ?? null,
    accountAvatarUrl: row.accountAvatarUrl ?? null,
    ...(row.permanentLive !== undefined ? { permanentLive: row.permanentLive } : {}),
    ...(row.liveSaveReplay !== undefined ? { liveSaveReplay: row.liveSaveReplay } : {})
  };
}

/** Model an existing-row refresh with an explicitly successful detail source. */
function metadataRefresh(row: VideoUpsertRow): ExistingVideoRefresh {
  return { base: row, detail: metadataDetailPatch(row) };
}

test("crawler additive metadata migration preserves rows and is idempotent", () => {
  const temp = createTempDb("crawler-metadata-migration");
  try {
    const db = new Database(temp.dbPath);
    db.exec(`
      CREATE TABLE videos (
        video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER,
        instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT,
        channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT,
        description TEXT, tags_json TEXT, category TEXT, published_at INTEGER,
        video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT,
        views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER,
        nsfw INTEGER, preview_path TEXT, last_checked_at INTEGER NOT NULL,
        last_error TEXT, last_error_at INTEGER, error_count INTEGER NOT NULL DEFAULT 0,
        invalid_reason TEXT, invalid_at INTEGER,
        PRIMARY KEY (video_id, instance_domain)
      );
      INSERT INTO videos(video_id, video_uuid, instance_domain, title, last_checked_at)
      VALUES ('v1', 'uuid-1', 'example.org', 'kept', 1);
    `);
    db.close();

    new VideoStore({ dbPath: temp.dbPath }).close();
    const first = new Database(temp.dbPath, { readonly: true });
    const columns1 = first.prepare("PRAGMA table_info(videos)").all() as Array<{ name: string }>;
    const migrated = first.prepare(
      "SELECT title, metadata_version FROM videos WHERE video_id='v1'"
    ).get() as { title: string; metadata_version: number };
    first.close();

    assert.equal(migrated.title, "kept");
    assert.equal(migrated.metadata_version, 0);
    assert.ok(columns1.some((column) => column.name === "language"));
    assert.ok(columns1.some((column) => column.name === "metadata_version"));

    new VideoStore({ dbPath: temp.dbPath }).close();
    const second = new Database(temp.dbPath, { readonly: true });
    const columns2 = second.prepare("PRAGMA table_info(videos)").all() as Array<{ name: string }>;
    second.close();
    assert.deepEqual(columns2.map((column) => column.name), columns1.map((column) => column.name));
  } finally {
    temp.cleanup();
  }
});

test("category id only follows an unchanged protected category label", () => {
  const temp = createTempDb("crawler-category-pair");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([metadataRow()]);
    store.refreshExistingVideoMetadata([
      metadataRefresh(metadataRow({
        category: "Gaming",
        categoryId: "15",
        metadataVersion: 1,
      }))
    ]);
    assert.deepEqual(
      getRow<{ category: string; category_id: string | null; metadata_version: number }>(
        temp.dbPath,
        "SELECT category, category_id, metadata_version FROM videos WHERE video_id='v1'"
      ),
      { category: "Music", category_id: null, metadata_version: 1 }
    );

    store.refreshExistingVideoMetadata([
      metadataRefresh(metadataRow({
        category: "Music",
        categoryId: "3",
        metadataVersion: 1,
      }))
    ]);
    assert.equal(
      getRow<{ category_id: string }>(
        temp.dbPath,
        "SELECT category_id FROM videos WHERE video_id='v1'"
      ).category_id,
      "3"
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("existing video channel tuple is preserved across a real channel move", () => {
  const temp = createTempDb("crawler-channel-tuple");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([metadataRow()]);
    store.refreshExistingVideoMetadata([
      metadataRefresh(metadataRow({
        channelId: "c2",
        channelUrl: "https://example.org/video-channels/gaming",
        channelName: "Gaming",
        metadataVersion: 1,
      }))
    ]);
    assert.deepEqual(
      getRow<{ channel_id: string; channel_url: string; channel_name: string; metadata_version: number }>(
        temp.dbPath,
        "SELECT channel_id, channel_url, channel_name, metadata_version FROM videos WHERE video_id='v1'"
      ),
      {
        channel_id: "c1",
        channel_url: "https://example.org/video-channels/music",
        channel_name: "Music",
        metadata_version: 1
      }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("same channel id can fill a previously missing channel URL without changing channel name", () => {
  const temp = createTempDb("crawler-channel-fill");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([metadataRow({ channelUrl: null })]);
    store.refreshExistingVideoMetadata([
      metadataRefresh(metadataRow({
        channelId: "c1",
        channelUrl: "https://example.org/video-channels/music",
        channelName: "Renamed Music",
        metadataVersion: 1,
      }))
    ]);
    assert.deepEqual(
      getRow<{ channel_id: string; channel_url: string; channel_name: string }>(
        temp.dbPath,
        "SELECT channel_id, channel_url, channel_name FROM videos WHERE video_id='v1'"
      ),
      {
        channel_id: "c1",
        channel_url: "https://example.org/video-channels/music",
        channel_name: "Music"
      }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("failed enrichment preserves last-known-good metadata and never lowers metadata version", () => {
  const temp = createTempDb("crawler-metadata-monotonic");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([
      metadataRow({
        language: "en",
        languageLabel: "English",
        licenceId: "1",
        licence: "Attribution",
        support: "support me",
        permanentLive: 1,
        liveSaveReplay: 0,
        metadataVersion: 1
      })
    ]);
    store.refreshExistingVideoMetadata([
      { base: metadataRow({
        language: null,
        languageLabel: null,
        licenceId: null,
        licence: null,
        support: null,
        permanentLive: null,
        liveSaveReplay: null,
        metadataVersion: 0,
        views: 99
      }) }
    ]);
    assert.deepEqual(
      getRow<{
        language: string; licence: string; support: string;
        permanent_live: number; live_save_replay: number; metadata_version: number; views: number;
      }>(
        temp.dbPath,
        `SELECT language, licence, support, permanent_live, live_save_replay,
                metadata_version, views FROM videos WHERE video_id='v1'`
      ),
      {
        language: "en",
        licence: "Attribution",
        support: "support me",
        permanent_live: 1,
        live_save_replay: 0,
        metadata_version: 1,
        views: 99
      }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("metadata backfill rolls channel owner and video checkpoint back together", () => {
  const temp = createTempDb("crawler-metadata-atomic");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([metadataRow()]);
    const db = new Database(temp.dbPath);
    db.exec(`
      CREATE TRIGGER fail_metadata_video_update
      BEFORE UPDATE ON videos
      WHEN NEW.metadata_version = 1
      BEGIN
        SELECT RAISE(ABORT, 'injected video update failure');
      END;
    `);
    db.close();

    assert.throws(
      () => store.applyMetadataBackfill(metadataRefresh(metadataRow({
        accountUsername: "alice-new",
        accountName: "Alice New",
        accountUrl: "https://example.org/accounts/alice-new",
        accountAvatarUrl: "https://example.org/alice.jpg",
        language: "en",
        metadataVersion: 1
      }))),
      /injected video update failure/
    );

    assert.deepEqual(
      getRow<{ owner_account_username: string | null; owner_account_url: string | null }>(
        temp.dbPath,
        "SELECT owner_account_username, owner_account_url FROM channels WHERE channel_id='c1'"
      ),
      { owner_account_username: null, owner_account_url: null }
    );
    assert.equal(
      getRow<{ metadata_version: number }>(
        temp.dbPath,
        "SELECT metadata_version FROM videos WHERE video_id='v1'"
      ).metadata_version,
      0
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("metadata validate-only opening never mutates a stale or current schema", () => {
  const stale = createTempDb("crawler-metadata-stale");
  const current = createTempDb("crawler-metadata-current");
  try {
    const staleDb = new Database(stale.dbPath);
    staleDb.exec(`
      CREATE TABLE videos(video_id TEXT NOT NULL, instance_domain TEXT NOT NULL,
        PRIMARY KEY(video_id, instance_domain));
      CREATE TABLE channels(channel_id TEXT NOT NULL, instance_domain TEXT NOT NULL,
        PRIMARY KEY(channel_id, instance_domain));
    `);
    const staleVersion = staleDb.pragma("schema_version", { simple: true }) as number;
    staleDb.close();

    assert.throws(() => assertMetadataMaintenanceSchema(stale.dbPath), /migrate-whitelist\.py/);
    const staleAfter = new Database(stale.dbPath, { readonly: true });
    assert.equal(staleAfter.pragma("schema_version", { simple: true }), staleVersion);
    assert.equal(
      (staleAfter.prepare("PRAGMA table_info(videos)").all() as Array<{ name: string }>).some(
        (column) => column.name === "language"
      ),
      false
    );
    staleAfter.close();

    new VideoStore({ dbPath: current.dbPath }).close();
    const before = new Database(current.dbPath, { readonly: true });
    const currentVersion = before.pragma("schema_version", { simple: true }) as number;
    before.close();
    assertMetadataMaintenanceSchema(current.dbPath);
    new VideoStore({ dbPath: current.dbPath, initializeSchema: false }).close();
    const after = new Database(current.dbPath, { readonly: true });
    assert.equal(after.pragma("schema_version", { simple: true }), currentVersion);
    after.close();
  } finally {
    stale.cleanup();
    current.cleanup();
  }
});
