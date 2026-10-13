/**
 * Characterization tests for video crawler database persistence.
 */

import assert from "node:assert/strict";
import test from "node:test";
import Database from "better-sqlite3";

import { ChannelStore } from "../../src/db/channels.js";
import type {
  ExistingVideoRefresh,
  NewVideoInsertRow,
  VideoChannelRow,
  VideoDetailMetadataPatch,
  VideoUpsertRow
} from "../../src/db/types.js";
import {
  UPDATER_STAGING_ROLE,
  VIDEO_AVAILABILITY_SEMANTICS_KEY,
  VIDEO_AVAILABILITY_SEMANTICS_VALUE,
  VIDEO_CORPUS_ROLE_KEY,
  VideoStore
} from "../../src/db/videos.js";
import { assertMetadataMaintenanceSchema, assertThumbnailMaintenanceSchema } from "../../src/db/schema.js";
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
  thumbnailCandidatesJson: null,
  embedPath: "/videos/embed/uuid-1",
  views: 10,
  likes: 2,
  dislikes: 0,
  commentsCount: null,
  nsfw: 0,
  previewPath: "/lazy-static/previews/uuid.jpg",
  lastCheckedAt: 100
};

function liveInsert(row: VideoUpsertRow): NewVideoInsertRow {
  return { row, initialInvalidity: { reason: null, observedAt: null } };
}

function absentInsert(
  row: VideoUpsertRow,
  reason: "not_found" | "gone",
  observedAt: number
): NewVideoInsertRow {
  return { row, initialInvalidity: { reason, observedAt } };
}

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
    store.insertNewVideos([liveInsert(video)]);
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

    // Historical availability fixtures are seeded directly; diagnostics have
    // no authority to change the canonical pair.
    const fixture = new Database(temp.dbPath);
    fixture.prepare("UPDATE videos SET invalid_reason='not_found',invalid_at=123 WHERE video_id='v1'").run();
    fixture.close();
    store.updateVideoError("v1", "example.org", "not_found");
    store.updateVideoError("v1", "example.org", "TLS failure");
    assert.deepEqual(getRow(temp.dbPath, "SELECT invalid_reason,invalid_at,error_count,last_error FROM videos WHERE video_id='v1'"), {
      invalid_reason: "not_found", invalid_at: 123, error_count: 2, last_error: "TLS failure"
    });
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("new video initial invalidity is atomic and insert conflicts remain no-ops", () => {
  const temp = createTempDb("crawler-videos-initial-invalidity");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    const observer = new Database(temp.dbPath);
    observer.exec(`
      CREATE TABLE insert_observations(video_id TEXT, invalid_reason TEXT, invalid_at INTEGER);
      CREATE TRIGGER observe_video_insert
      AFTER INSERT ON videos
      BEGIN
        INSERT INTO insert_observations(video_id, invalid_reason, invalid_at)
        VALUES (NEW.video_id, NEW.invalid_reason, NEW.invalid_at);
      END;
    `);
    observer.close();

    const observedAt = 123456;
    store.insertNewVideos([absentInsert(video, "not_found", observedAt)]);
    assert.deepEqual(
      getRow(temp.dbPath, "SELECT invalid_reason, invalid_at, last_error, last_error_at, error_count FROM videos WHERE video_id='v1'"),
      {
        invalid_reason: "not_found",
        invalid_at: observedAt,
        last_error: "not_found",
        last_error_at: observedAt,
        error_count: 1
      }
    );
    assert.deepEqual(
      allRows(temp.dbPath, "SELECT video_id, invalid_reason, invalid_at FROM insert_observations ORDER BY video_id"),
      [{ video_id: "v1", invalid_reason: "not_found", invalid_at: observedAt }]
    );

    store.insertNewVideos([liveInsert({ ...video, videoId: "v2", videoUuid: "uuid-2" })]);
    assert.deepEqual(
      getRow(temp.dbPath, "SELECT invalid_reason, invalid_at, error_count FROM videos WHERE video_id='v2'"),
      { invalid_reason: null, invalid_at: null, error_count: 0 }
    );
    assert.deepEqual(
      getRow(temp.dbPath, "SELECT invalid_reason, invalid_at FROM insert_observations WHERE video_id='v2'"),
      { invalid_reason: null, invalid_at: null }
    );

    // INSERT OR IGNORE owns identity conflicts. A later candidate with a
    // different absence observation cannot mutate the already committed row.
    store.insertNewVideos([
      absentInsert({ ...video, title: "wrong replacement" }, "gone", observedAt + 1)
    ]);
    assert.deepEqual(
      getRow(temp.dbPath, "SELECT title, invalid_reason, invalid_at, error_count FROM videos WHERE video_id='v1'"),
      {
        title: "Song",
        invalid_reason: "not_found",
        invalid_at: observedAt,
        error_count: 1
      }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("live initial state cannot carry an invalidity timestamp", () => {
  const temp = createTempDb("crawler-videos-invalid-live-state");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    assert.throws(
      () => store.insertNewVideos([{
        row: video,
        initialInvalidity: { reason: null, observedAt: 1 }
      } as unknown as NewVideoInsertRow]),
      /live initial video state/u
    );
    assert.equal(allRows(temp.dbPath, "SELECT * FROM videos").length, 0);
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("first standalone insert atomically mints only current writer evidence", () => {
  const temp = createTempDb("crawler-videos-writer-evidence");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([liveInsert(video)]);
    assert.deepEqual(
      allRows(temp.dbPath, "SELECT key, value FROM crawl_state ORDER BY key"),
      [{ key: VIDEO_AVAILABILITY_SEMANTICS_KEY, value: VIDEO_AVAILABILITY_SEMANTICS_VALUE }]
    );
    assert.equal(allRows(temp.dbPath, "SELECT * FROM videos").length, 1);

    store.insertNewVideos([liveInsert({ ...video, videoId: "v2", videoUuid: "uuid-2" })]);
    assert.equal(allRows(temp.dbPath, "SELECT * FROM videos").length, 2);
    assert.equal(
      allRows(temp.dbPath, "SELECT * FROM crawl_state WHERE key = ?", VIDEO_CORPUS_ROLE_KEY).length,
      0
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("empty insert batch does not mint writer evidence or corpus role", () => {
  const temp = createTempDb("crawler-videos-empty-batch");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([]);
    assert.equal(
      getRow<{ count: number }>(temp.dbPath, "SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table' AND name='crawl_state'").count,
      0
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("updater staging inserts preserve its explicit role and require current semantics", () => {
  const temp = createTempDb("crawler-videos-updater-role");
  try {
    const db = new Database(temp.dbPath);
    db.exec("CREATE TABLE crawl_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
    db.prepare("INSERT INTO crawl_state(key, value) VALUES (?, ?)").run(
      VIDEO_AVAILABILITY_SEMANTICS_KEY,
      VIDEO_AVAILABILITY_SEMANTICS_VALUE
    );
    db.prepare("INSERT INTO crawl_state(key, value) VALUES (?, ?)").run(
      VIDEO_CORPUS_ROLE_KEY,
      UPDATER_STAGING_ROLE
    );
    db.close();

    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([liveInsert(video)]);
    assert.deepEqual(
      getRow(temp.dbPath, "SELECT value FROM crawl_state WHERE key = ?", VIDEO_CORPUS_ROLE_KEY),
      { value: UPDATER_STAGING_ROLE }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("updater staging role cannot repair missing or pre-cutover writer semantics", () => {
  for (const semantics of [null, "canonical_absence_v1"]) {
    const temp = createTempDb(`crawler-videos-updater-incompatible-${semantics ?? "missing"}`);
    try {
      const db = new Database(temp.dbPath);
      db.exec("CREATE TABLE crawl_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
      db.prepare("INSERT INTO crawl_state(key, value) VALUES (?, ?)").run(
        VIDEO_CORPUS_ROLE_KEY,
        UPDATER_STAGING_ROLE
      );
      if (semantics !== null) {
        db.prepare("INSERT INTO crawl_state(key, value) VALUES (?, ?)").run(
          VIDEO_AVAILABILITY_SEMANTICS_KEY,
          semantics
        );
      }
      db.close();

      const store = new VideoStore({ dbPath: temp.dbPath });
      assert.throws(
        () => store.insertNewVideos([liveInsert(video)]),
        /updater staging video corpus has incompatible writer semantics/u
      );
      assert.equal(allRows(temp.dbPath, "SELECT * FROM videos").length, 0);
      assert.deepEqual(
        allRows(temp.dbPath, "SELECT key, value FROM crawl_state ORDER BY key"),
        semantics === null
          ? [{ key: VIDEO_CORPUS_ROLE_KEY, value: UPDATER_STAGING_ROLE }]
          : [
              { key: VIDEO_AVAILABILITY_SEMANTICS_KEY, value: semantics },
              { key: VIDEO_CORPUS_ROLE_KEY, value: UPDATER_STAGING_ROLE }
            ]
      );
      store.close();
    } finally {
      temp.cleanup();
    }
  }
});

test("empty standalone corpus with explicit old writer evidence is not upgraded in place", () => {
  const temp = createTempDb("crawler-videos-empty-old-writer");
  try {
    const db = new Database(temp.dbPath);
    db.exec("CREATE TABLE crawl_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
    db.prepare("INSERT INTO crawl_state(key, value) VALUES (?, ?)").run(
      VIDEO_AVAILABILITY_SEMANTICS_KEY,
      "canonical_absence_v1"
    );
    db.close();

    const store = new VideoStore({ dbPath: temp.dbPath });
    assert.throws(
      () => store.insertNewVideos([liveInsert(video)]),
      /video corpus has incompatible writer semantics/u
    );
    assert.equal(allRows(temp.dbPath, "SELECT * FROM videos").length, 0);
    assert.deepEqual(allRows(temp.dbPath, "SELECT key, value FROM crawl_state"), [
      { key: VIDEO_AVAILABILITY_SEMANTICS_KEY, value: "canonical_absence_v1" }
    ]);
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("writer authorization rejects unknown roles and pre-cutover non-empty corpora without mutation", () => {
  const unknownRole = createTempDb("crawler-videos-unknown-role");
  try {
    const db = new Database(unknownRole.dbPath);
    db.exec("CREATE TABLE crawl_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
    db.prepare("INSERT INTO crawl_state(key, value) VALUES (?, ?)").run(VIDEO_CORPUS_ROLE_KEY, "future_role");
    db.close();
    const store = new VideoStore({ dbPath: unknownRole.dbPath });
    assert.throws(() => store.insertNewVideos([liveInsert(video)]), /unsupported video corpus role/u);
    assert.equal(allRows(unknownRole.dbPath, "SELECT * FROM videos").length, 0);
    assert.deepEqual(allRows(unknownRole.dbPath, "SELECT key, value FROM crawl_state"), [
      { key: VIDEO_CORPUS_ROLE_KEY, value: "future_role" }
    ]);
    store.close();
  } finally {
    unknownRole.cleanup();
  }

  const legacy = createTempDb("crawler-videos-legacy-corpus");
  try {
    // Seed a legacy row directly so the new writer is not allowed to certify
    // the corpus merely because it has now been opened by current code.
    const seed = new VideoStore({ dbPath: legacy.dbPath });
    seed.close();
    const db = new Database(legacy.dbPath);
    db.prepare(
      "INSERT INTO videos(video_id, instance_domain, last_checked_at) VALUES ('legacy', 'example.org', 1)"
    ).run();
    db.close();

    const store = new VideoStore({ dbPath: legacy.dbPath });
    assert.throws(
      () => store.insertNewVideos([liveInsert({ ...video, videoId: "v2", videoUuid: "uuid-2" })]),
      /predates current atomic initial-tombstone/u
    );
    assert.equal(allRows(legacy.dbPath, "SELECT video_id FROM videos ORDER BY video_id").length, 1);
    assert.equal(
      getRow<{ count: number }>(legacy.dbPath, "SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table' AND name='crawl_state'").count,
      0
    );
    store.close();
  } finally {
    legacy.cleanup();
  }
});

test("writer evidence rolls back when the first insert batch fails", () => {
  const temp = createTempDb("crawler-videos-writer-rollback");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    const invalidRow = { ...video, instanceDomain: null } as unknown as VideoUpsertRow;
    assert.throws(() => store.insertNewVideos([liveInsert(invalidRow)]));
    assert.equal(allRows(temp.dbPath, "SELECT * FROM videos").length, 0);
    assert.equal(
      getRow<{ count: number }>(temp.dbPath, "SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table' AND name='crawl_state'").count,
      0
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("VideoStore persists authoritative candidate objects and resumes only SQL NULL rows", () => {
  const temp = createTempDb("crawler-videos-thumbnails");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([liveInsert(video)]);

    assert.deepEqual(store.listVideosForThumbnailRefresh(true), [
      {
        videoId: "v1",
        videoUuid: "uuid-1",
        instanceDomain: "example.org"
      }
    ]);

    store.updateVideoThumbnailCandidates(
      "v1",
      "example.org",
      [
        { url: "https://example.org/850.jpg", width: 850, height: 480 },
        { url: "https://example.org/280.jpg", width: 280, height: 157 }
      ],
      200
    );
    assert.deepEqual(
      getRow<{
        thumbnail_candidates_json: string; thumbnail_url: string;
        thumbnail_width: number; thumbnail_height: number; last_checked_at: number;
      }>(
        temp.dbPath,
        `SELECT thumbnail_candidates_json, thumbnail_url, thumbnail_width,
                thumbnail_height, last_checked_at
         FROM videos WHERE video_id = ? AND instance_domain = ?`,
        "v1",
        "example.org"
      ),
      {
        thumbnail_candidates_json: JSON.stringify([
          { url: "https://example.org/850.jpg", width: 850, height: 480 },
          { url: "https://example.org/280.jpg", width: 280, height: 157 }
        ]),
        thumbnail_url: "https://example.org/850.jpg",
        thumbnail_width: 850,
        thumbnail_height: 480,
        last_checked_at: 200
      }
    );
    assert.deepEqual(store.listVideosForThumbnailRefresh(true), []);

    store.updateVideoThumbnailCandidates("v1", "example.org", [], 300);
    assert.deepEqual(
      getRow<{ thumbnail_candidates_json: string; thumbnail_url: string | null; thumbnail_width: number | null }>(
        temp.dbPath,
        "SELECT thumbnail_candidates_json, thumbnail_url, thumbnail_width FROM videos WHERE video_id = ? AND instance_domain = ?",
        "v1",
        "example.org"
      ),
      { thumbnail_candidates_json: "[]", thumbnail_url: null, thumbnail_width: null }
    );

    store.close();
  } finally {
    temp.cleanup();
  }
});

test("VideoStore thumbnail refresh excludes definitively invalid videos", () => {
  const temp = createTempDb("crawler-videos-thumbnail-invalid");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([liveInsert(video)]);
    const fixture = new Database(temp.dbPath);
    fixture.prepare("UPDATE videos SET invalid_reason='not_found',invalid_at=123 WHERE video_id='v1'").run();
    fixture.close();

    assert.deepEqual(store.listVideosForThumbnailRefresh(false), []);
    assert.deepEqual(store.listVideosForThumbnailRefresh(true), []);
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("base refresh never overwrites authoritative thumbnail state", () => {
  const temp = createTempDb("crawler-videos-thumbnail-base-refresh");
  try {
    seedChannel(temp.dbPath);
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([liveInsert(video)]);
    store.updateVideoThumbnailCandidates(
      "v1",
      "example.org",
      [{ url: "https://example.org/good.jpg", width: 850, height: 480 }],
      200
    );
    store.refreshExistingVideoMetadata([{
      base: {
        ...video,
        thumbnailUrl: "https://example.org/list-stale.jpg",
        thumbnailCandidatesJson: null,
        thumbnailWidth: 1,
        thumbnailHeight: 1,
        lastCheckedAt: 500
      }
    }]);
    assert.deepEqual(
      getRow<{ thumbnail_candidates_json: string; thumbnail_url: string }>(
        temp.dbPath,
        "SELECT thumbnail_candidates_json, thumbnail_url FROM videos WHERE video_id='v1'"
      ),
      {
        thumbnail_candidates_json: '[{"url":"https://example.org/good.jpg","width":850,"height":480}]',
        thumbnail_url: "https://example.org/good.jpg"
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
    thumbnailCandidatesJson: null,
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
      "SELECT title, metadata_version, thumbnail_candidates_json FROM videos WHERE video_id='v1'"
    ).get() as { title: string; metadata_version: number; thumbnail_candidates_json: string | null };
    first.close();

    assert.equal(migrated.title, "kept");
    assert.equal(migrated.metadata_version, 0);
    assert.equal(migrated.thumbnail_candidates_json, null);
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



test("legacy video table rebuild preserves existing thumbnail candidate state", () => {
  const temp = createTempDb("crawler-thumbnail-rebuild-preserve");
  try {
    const db = new Database(temp.dbPath);
    db.exec(`
      CREATE TABLE videos (
        video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER,
        instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT,
        channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT,
        description TEXT, tags_json TEXT, category TEXT, published_at INTEGER,
        video_url TEXT, duration INTEGER, thumbnail_url TEXT, thumbnail_candidates_json TEXT,
        thumbnail_width INTEGER, thumbnail_height INTEGER,
        embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER,
        nsfw INTEGER, preview_path TEXT, last_checked_at INTEGER NOT NULL,
        invalid_reason TEXT, invalid_at INTEGER,
        PRIMARY KEY (video_id, instance_domain)
      );
      INSERT INTO videos(
        video_id, video_uuid, instance_domain, thumbnail_url, thumbnail_candidates_json,
        thumbnail_width, thumbnail_height, last_checked_at
      ) VALUES (
        'v1', 'uuid-1', 'example.org', 'https://example.org/a.jpg',
        '[{"url":"https://example.org/a.jpg","width":850,"height":480},{"url":"https://example.org/b.jpg","width":280,"height":157}]', 850, 480, 1
      );
    `);
    db.close();

    // Missing generic error columns force the legacy table-rebuild path.
    new VideoStore({ dbPath: temp.dbPath }).close();

    assert.deepEqual(
      getRow<{
        thumbnail_candidates_json: string; thumbnail_url: string;
        thumbnail_width: number; thumbnail_height: number;
      }>(
        temp.dbPath,
        `SELECT thumbnail_candidates_json, thumbnail_url, thumbnail_width, thumbnail_height
         FROM videos WHERE video_id='v1'`
      ),
      {
        thumbnail_candidates_json: '[{"url":"https://example.org/a.jpg","width":850,"height":480},{"url":"https://example.org/b.jpg","width":280,"height":157}]',
        thumbnail_url: "https://example.org/a.jpg",
        thumbnail_width: 850,
        thumbnail_height: 480
      }
    );
  } finally {
    temp.cleanup();
  }
});

test("legacy video table rebuild adds missing thumbnail mirror dimensions as null", () => {
  const temp = createTempDb("crawler-thumbnail-rebuild-missing-dimensions");
  try {
    const db = new Database(temp.dbPath);
    db.exec(`
      CREATE TABLE videos (
        video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER,
        instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT,
        channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT,
        description TEXT, tags_json TEXT, category TEXT, published_at INTEGER,
        video_url TEXT, duration INTEGER, thumbnail_url TEXT, thumbnail_candidates_json TEXT,
        embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER,
        nsfw INTEGER, preview_path TEXT, last_checked_at INTEGER NOT NULL,
        invalid_reason TEXT, invalid_at INTEGER,
        PRIMARY KEY (video_id, instance_domain)
      );
      INSERT INTO videos(
        video_id, video_uuid, instance_domain, thumbnail_url, thumbnail_candidates_json, last_checked_at
      ) VALUES (
        'v1', 'uuid-1', 'example.org', 'https://example.org/a.jpg',
        '[{"url":"https://example.org/a.jpg","width":850,"height":480}]', 1
      );
    `);
    db.close();

    new VideoStore({ dbPath: temp.dbPath }).close();

    assert.deepEqual(
      getRow<{
        thumbnail_candidates_json: string; thumbnail_url: string;
        thumbnail_width: number | null; thumbnail_height: number | null;
      }>(
        temp.dbPath,
        `SELECT thumbnail_candidates_json, thumbnail_url, thumbnail_width, thumbnail_height
         FROM videos WHERE video_id='v1'`
      ),
      {
        thumbnail_candidates_json: '[{"url":"https://example.org/a.jpg","width":850,"height":480}]',
        thumbnail_url: "https://example.org/a.jpg",
        thumbnail_width: null,
        thumbnail_height: null
      }
    );
  } finally {
    temp.cleanup();
  }
});


test("category id only follows an unchanged protected category label", () => {
  const temp = createTempDb("crawler-category-pair");
  try {
    const store = new VideoStore({ dbPath: temp.dbPath });
    store.insertNewVideos([liveInsert(metadataRow())]);
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
    store.insertNewVideos([liveInsert(metadataRow())]);
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
    store.insertNewVideos([liveInsert(metadataRow({ channelUrl: null }))]);
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
      liveInsert(metadataRow({
        language: "en",
        languageLabel: "English",
        licenceId: "1",
        licence: "Attribution",
        support: "support me",
        permanentLive: 1,
        liveSaveReplay: 0,
        metadataVersion: 1
      }))
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
    store.insertNewVideos([liveInsert(metadataRow())]);
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


test("thumbnail maintenance validates schema read-only before network work", () => {
  const stale = createTempDb("crawler-thumbnails-stale");
  const current = createTempDb("crawler-thumbnails-current");
  try {
    const staleDb = new Database(stale.dbPath);
    staleDb.exec(`
      CREATE TABLE videos(
        video_id TEXT NOT NULL, video_uuid TEXT, instance_domain TEXT NOT NULL,
        thumbnail_url TEXT, thumbnail_width INTEGER, thumbnail_height INTEGER,
        PRIMARY KEY(video_id, instance_domain)
      );
    `);
    const staleVersion = staleDb.pragma("schema_version", { simple: true }) as number;
    staleDb.close();

    assert.throws(() => assertThumbnailMaintenanceSchema(stale.dbPath), /migrate-whitelist\.py/);
    const staleAfter = new Database(stale.dbPath, { readonly: true });
    assert.equal(staleAfter.pragma("schema_version", { simple: true }), staleVersion);
    assert.equal(
      (staleAfter.prepare("PRAGMA table_info(videos)").all() as Array<{ name: string }>).some(
        (column) => column.name === "thumbnail_candidates_json"
      ),
      false
    );
    staleAfter.close();

    new VideoStore({ dbPath: current.dbPath }).close();
    const before = new Database(current.dbPath, { readonly: true });
    const currentVersion = before.pragma("schema_version", { simple: true }) as number;
    before.close();
    assertThumbnailMaintenanceSchema(current.dbPath);
    const after = new Database(current.dbPath, { readonly: true });
    assert.equal(after.pragma("schema_version", { simple: true }), currentVersion);
    after.close();
  } finally {
    stale.cleanup();
    current.cleanup();
  }
});
