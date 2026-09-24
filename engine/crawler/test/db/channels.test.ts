/**
 * Characterization tests for channel crawler database persistence.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ChannelStore } from "../../src/db/channels.js";
import { allRows, createTempDb, getRow } from "./helpers.js";

const channel = {
  channelId: "c1",
  channelName: "music",
  channelUrl: "https://example.org/video-channels/music",
  displayName: "Music",
  instanceDomain: "example.org",
  videosCount: null,
  followersCount: 10,
  avatarUrl: "https://example.org/avatar.png"
};

test("ChannelStore applies schema and lists instances in current order", () => {
  const temp = createTempDb("crawler-channels-list");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.markInstanceDone("b.example");
    store.markInstanceDone("a.example");
    assert.deepEqual(store.listInstances(), ["a.example", "b.example"]);
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("ChannelStore preserves instance health and error fields", () => {
  const temp = createTempDb("crawler-channels-health");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.markInstanceError("example.org", "channels failed");
    assert.deepEqual(
      getRow<{ last_error: string; last_error_source: string }>(
        temp.dbPath,
        "SELECT last_error, last_error_source FROM instances WHERE host = ?",
        "example.org"
      ),
      { last_error: "channels failed", last_error_source: "channels" }
    );

    store.markInstanceHealthError("example.org", "down");
    assert.equal(
      getRow<{ health_status: string; health_error: string }>(
        temp.dbPath,
        "SELECT health_status, health_error FROM instances WHERE host = ?",
        "example.org"
      ).health_status,
      "error"
    );

    store.markInstanceHealthOk("example.org");
    assert.deepEqual(
      getRow<{ health_status: string; health_error: string | null }>(
        temp.dbPath,
        "SELECT health_status, health_error FROM instances WHERE host = ?",
        "example.org"
      ),
      { health_status: "ok", health_error: null }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("ChannelStore upserts channels and preserves progress/videos_count behavior", () => {
  const temp = createTempDb("crawler-channels-upsert");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.markInstanceDone("example.org");
    store.upsertChannels([channel]);
    store.upsertChannels([{ ...channel, displayName: "Updated", followersCount: 12 }]);
    assert.equal(
      allRows(temp.dbPath, "SELECT * FROM channels WHERE channel_id = ?", "c1").length,
      1
    );
    assert.deepEqual(
      getRow<{ display_name: string; followers_count: number }>(
        temp.dbPath,
        "SELECT display_name, followers_count FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        "example.org"
      ),
      { display_name: "Updated", followers_count: 12 }
    );

    store.prepareChannelProgress(["example.org"], false);
    assert.deepEqual(store.listChannelWorkItems(), [
      { instanceDomain: "example.org", status: "pending", lastStart: 0 }
    ]);
    store.updateChannelProgress("example.org", "in_progress", 123);
    assert.equal(
      getRow<{ status: string; last_start: number }>(
        temp.dbPath,
        "SELECT status, last_start FROM channel_crawl_progress WHERE instance_domain = ?",
        "example.org"
      ).last_start,
      123
    );
    store.updateChannelProgress("example.org", "error", 123);
    assert.deepEqual(store.listChannelWorkItems(["error"]), [
      { instanceDomain: "example.org", status: "error", lastStart: 123 }
    ]);

    store.updateChannelVideosCount("c1", "example.org", 5);
    assert.equal(
      getRow<{ videos_count: number }>(
        temp.dbPath,
        "SELECT videos_count FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        "example.org"
      ).videos_count,
      5
    );

    store.updateChannelVideosCountError("c1", "example.org", "ignored");
    assert.equal(
      getRow<{ last_error: string | null }>(
        temp.dbPath,
        "SELECT last_error FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        "example.org"
      ).last_error,
      null
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("ChannelStore preserves channel health fields", () => {
  const temp = createTempDb("crawler-channels-row-health");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.upsertChannels([channel]);
    store.updateChannelHealthError("c1", "example.org", "channel down");
    assert.equal(
      getRow<{ health_status: string; health_error: string }>(
        temp.dbPath,
        "SELECT health_status, health_error FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        "example.org"
      ).health_error,
      "channel down"
    );
    store.updateChannelHealthOk("c1", "example.org");
    assert.deepEqual(
      getRow<{ health_status: string; health_error: string | null }>(
        temp.dbPath,
        "SELECT health_status, health_error FROM channels WHERE channel_id = ? AND instance_domain = ?",
        "c1",
        "example.org"
      ),
      { health_status: "ok", health_error: null }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("ChannelStore count resume selects only unfinished rows and isolates recorded errors", () => {
  const temp = createTempDb("crawler-channel-count-resume");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.upsertChannels([
      { ...channel, channelId: "done", channelName: "done", videosCount: 4 },
      { ...channel, channelId: "pending", channelName: "pending", videosCount: null },
      { ...channel, channelId: "failed", channelName: "failed", videosCount: null }
    ]);
    store.updateChannelVideosCountError("failed", "example.org", "[timeout] prior failure");

    assert.deepEqual(
      store.listChannelsForVideoCount("example.org", true, false).map((row) => row.channel_id),
      ["pending"]
    );
    assert.deepEqual(
      store.listChannelsForVideoCount("example.org", true, true).map((row) => row.channel_id),
      ["failed"]
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("ChannelStore refreshes only the listed count and clears a resolved count error", () => {
  const temp = createTempDb("crawler-channel-listed-count");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.upsertChannels([{ ...channel, videosCount: 5 }]);

    store.refreshChannelVideoCountsFromListing([{ ...channel, videosCount: null }]);
    store.updateChannelVideosCountError("c1", "example.org", "[timeout] count failed");
    store.refreshChannelVideoCountsFromListing([{ ...channel, videosCount: 7 }]);

    assert.deepEqual(
      getRow<{
        videos_count: number;
        display_name: string;
        last_error: string | null;
        last_error_source: string | null;
      }>(
        temp.dbPath,
        `SELECT videos_count, display_name, last_error, last_error_source
         FROM channels WHERE channel_id = ? AND instance_domain = ?`,
        "c1",
        "example.org"
      ),
      {
        videos_count: 7,
        display_name: "Music",
        last_error: null,
        last_error_source: null
      }
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("ChannelStore reports withVideos as channels whose count is positive", () => {
  const temp = createTempDb("crawler-channel-positive-counts");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.upsertChannels([
      { ...channel, channelId: "positive", videosCount: 3 },
      { ...channel, channelId: "empty", videosCount: 0 },
      { ...channel, channelId: "unknown", videosCount: null }
    ]);

    assert.deepEqual(store.getChannelCounts(), {
      total: 3,
      withVideos: 1,
      withError: 0
    });
    store.close();
  } finally {
    temp.cleanup();
  }
});

test("ChannelStore scoped resume preserves progress belonging to other hosts", () => {
  const temp = createTempDb("crawler-channel-scoped-resume");
  try {
    const store = new ChannelStore({ dbPath: temp.dbPath });
    store.prepareChannelProgress(["a.example", "b.example"], false);
    store.updateChannelProgress("a.example", "done", 0);

    store.prepareChannelProgress(["b.example"], true, ["b.example"]);

    assert.deepEqual(store.listChannelWorkItems(["done"], ["a.example"]), [
      { instanceDomain: "a.example", status: "done", lastStart: 0 }
    ]);
    assert.deepEqual(store.listChannelWorkItems(["pending"], ["b.example"]), [
      { instanceDomain: "b.example", status: "pending", lastStart: 0 }
    ]);
    store.close();
  } finally {
    temp.cleanup();
  }
});
