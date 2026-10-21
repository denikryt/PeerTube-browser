/** Ordinary video-crawl channel paging must share the host-wide fatal stop signal. */
import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { VideoStore } from "../../src/db/videos.js";
import { crawlVideos, type VideoCrawlOptions } from "../../src/videos-worker.js";
import { NoNetworkError } from "../../src/http.js";

/** Two channels have fresh parent health, enumeration provenance and positive counts. */
function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "video-host-cancel-"));
  const dbPath = path.join(directory, "staging.db");
  new VideoStore({ dbPath }).close();
  const db = new Database(dbPath);
  db.exec("CREATE TABLE IF NOT EXISTS crawl_state (key TEXT PRIMARY KEY,value TEXT NOT NULL)");
  for (const host of ["a.test", "b.test"]) {
    db.prepare("INSERT INTO instances(host,health_status,health_checked_at) VALUES(?,'ok',123)").run(host);
    db.prepare("INSERT INTO channels(channel_id,channel_name,instance_domain,videos_count,health_status,health_checked_at) VALUES(?, 'channel', ?, 1,'ok',123)")
      .run(`channel-${host}`, host);
    db.prepare("INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) VALUES(?,'done',0,123)").run(host);
    db.prepare("INSERT INTO crawl_state(key,value) VALUES(?,'page_zero_complete_v1')")
      .run(`parent_enumeration_v1:${host}`);
  }
  db.close();
  const options: VideoCrawlOptions = {
    dbPath, hostsFile: null, excludeHostsFile: null, existingDbPath: null,
    concurrency: 2, hostConcurrency: 1, hostDelayMs: 0, timeoutMs: 100,
    maxRetries: 0, resume: false, errorsOnly: false, newOnly: false,
    stopAfterFullPages: 0, sort: "-publishedAt", maxInstances: 0,
    maxChannels: 0, maxVideosPages: 0, tagsOnly: false,
    updateTags: false, commentsOnly: false, refreshThumbnails: false,
  };
  return {dbPath, options, cleanup: () => fs.rmSync(directory,{recursive:true,force:true})};
}

test("fatal B instance stops A's next channel page without marking it done", async () => {
  const f = fixture(), old = globalThis.fetch;
  let releaseA: (() => void) | undefined;
  let signalA: (() => void) | undefined;
  const startedA = new Promise<void>(resolve => { signalA = resolve; });
  const allowA = new Promise<void>(resolve => { releaseA = resolve; });
  const requests: string[] = [];
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    requests.push(`${url.hostname}:${url.searchParams.get("start")}`);
    if (url.hostname === "b.test") {
      await startedA;
      setTimeout(() => releaseA?.(), 10);
      throw new NoNetworkError("confirmed local timeout");
    }
    signalA?.();
    await allowA;
    return new Response(JSON.stringify({total: 150,data: []}));
  };
  try {
    await assert.rejects(crawlVideos(f.options), /confirmed local timeout/);
    assert.deepEqual(requests.sort(), ["a.test:0", "b.test:0"]);
    const db = new Database(f.dbPath, {readonly:true});
    const state = db.prepare("SELECT status FROM video_crawl_progress WHERE instance_domain='a.test'").get() as any;
    assert.notEqual(state.status, "done");
    db.close();
  } finally {globalThis.fetch=old;f.cleanup();}
});

test("remote B error does not cancel healthy A channel pagination", async () => {
  const f = fixture(), old = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    requests.push(url.hostname);
    return url.hostname === "b.test" ? new Response("{}", {status:404})
      : new Response(JSON.stringify({total:0,data:[]}));
  };
  try {
    await crawlVideos(f.options);
    assert.deepEqual(requests.sort(),["a.test","b.test"]);
    const db = new Database(f.dbPath,{readonly:true});
    const rows = db.prepare("SELECT instance_domain,status FROM video_crawl_progress ORDER BY instance_domain").all();
    assert.deepEqual(rows,[{instance_domain:"a.test",status:"done"},{instance_domain:"b.test",status:"error"}]);
    db.close();
  } finally {globalThis.fetch=old;f.cleanup();}
});
