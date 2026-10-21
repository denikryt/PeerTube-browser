/** Run-wide outage cancellation across independently active video-maintenance hosts. */
import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { VideoStore } from "../src/db/videos.js";
import { crawlVideos, type VideoCrawlOptions } from "../src/videos-worker.js";
import { NoNetworkError } from "../src/http.js";

const baseOptions: Omit<VideoCrawlOptions, "dbPath"> = {
  hostsFile: null, excludeHostsFile: null, existingDbPath: null,
  concurrency: 2, hostConcurrency: 1, hostDelayMs: 0,
  timeoutMs: 100, maxRetries: 0, resume: false,
  errorsOnly: false, newOnly: false, stopAfterFullPages: 0,
  sort: "-publishedAt", maxInstances: 0, maxChannels: 0,
  maxVideosPages: 0, tagsOnly: false, updateTags: false,
  commentsOnly: true, refreshThumbnails: false,
};

/** Seed a real crawler database containing two hosts with pending comments. */
function commentsFixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "comments-outage-"));
  const dbPath = path.join(directory, "stage.db");
  new VideoStore({ dbPath }).close();
  const db = new Database(dbPath);
  for (const host of ["a.test", "b.test"]) {
    for (let i = 1; i <= 3; i++) {
      db.prepare("INSERT INTO videos(video_id,video_uuid,instance_domain,last_checked_at) VALUES(?,?,?,1)")
        .run(`${host}-${i}`, `u${i}`, host);
    }
  }
  db.close();
  return { dbPath, cleanup: () => fs.rmSync(directory, { recursive: true, force: true }) };
}

test("comments: outage in B stops new A requests but drains and persists A's in-flight result", async () => {
  const f = commentsFixture();
  const old = globalThis.fetch;
  const requests: string[] = [];
  let failed = false;
  let releaseA: (() => void) | undefined;
  const allowA = new Promise<void>(resolve => { releaseA = resolve; });
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    requests.push(`${url.hostname}/${url.pathname.split("/").at(-1)}`);
    if (url.hostname === "b.test") {
      failed = true;
      setTimeout(() => releaseA?.(), 10);
      throw new NoNetworkError("confirmed local outage");
    }
    await allowA;
    assert.equal(failed, true);
    return new Response(JSON.stringify({ uuid: url.pathname.split("/").at(-1), comments: 7 }));
  };
  try {
    await assert.rejects(crawlVideos({ ...baseOptions, dbPath: f.dbPath }), /confirmed local outage/);
    assert.deepEqual(requests.sort(), ["a.test/u1", "b.test/u1"]);
    const db = new Database(f.dbPath, { readonly: true });
    const updated = db.prepare("SELECT video_id,comments_count FROM videos WHERE comments_count IS NOT NULL").all();
    assert.deepEqual(updated, [{ video_id: "a.test-1", comments_count: 7 }]);
    db.close();
  } finally { globalThis.fetch = old; f.cleanup(); }
});

test("comments: target 404 on B preserves A's complete work and remains host-local", async () => {
  const f = commentsFixture();
  const old = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    requests.push(`${url.hostname}/${url.pathname.split("/").at(-1)}`);
    return url.hostname === "b.test" ? new Response("{}", { status: 404 })
      : new Response(JSON.stringify({ uuid: url.pathname.split("/").at(-1), comments: 9 }));
  };
  try {
    await crawlVideos({ ...baseOptions, dbPath: f.dbPath });
    assert.equal(requests.length, 6);
    const db = new Database(f.dbPath, { readonly: true });
    assert.equal((db.prepare("SELECT COUNT(*) n FROM videos WHERE instance_domain='a.test' AND comments_count=9").get() as any).n, 3);
    db.close();
  } finally { globalThis.fetch = old; f.cleanup(); }
});
