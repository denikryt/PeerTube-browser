/** Deterministic tests for REST-only live thumbnail candidate smoke orchestration. */

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import Database from "better-sqlite3";
import {
  assertLiveThumbnailSmoke,
  defaultLiveThumbnailSmokeOptions,
  runLiveThumbnailSmoke,
  type LiveThumbnailSmokeReport
} from "../../src/live-thumbnail-smoke.js";

/** Create the minimal candidate-state DB expected after a production crawler stage. */
function writeCandidateDb(
  dbPath: string,
  host: string,
  candidatesJson: string | null,
  thumbnailUrl: string | null
) {
  const db = new Database(dbPath);
  db.exec(`CREATE TABLE videos (
    video_id TEXT, video_uuid TEXT, instance_domain TEXT,
    thumbnail_url TEXT, thumbnail_candidates_json TEXT
  )`);
  db.prepare("INSERT INTO videos VALUES (?, ?, ?, ?, ?)").run(
    "video-1", "uuid-1", host, thumbnailUrl, candidatesJson
  );
  db.close();
}

test("runner validates ordered REST candidates without requesting image assets", async () => {
  const removed: string[] = [];
  const requested: string[] = [];
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thumbnail-smoke-unit-"));
  const report = await runLiveThumbnailSmoke({
    ...defaultLiveThumbnailSmokeOptions(), requiredHosts: 1, candidateLimit: 1
  }, {
    fetchRegistryHosts: async () => ["usable.example"],
    makeTempDir: () => root,
    removeDir: (dir) => { removed.push(dir); fs.rmSync(dir, { recursive: true, force: true }); },
    crawlInstances: async () => undefined,
    crawlChannelsStage: async () => undefined,
    crawlCountsStage: async () => undefined,
    crawlVideosStage: async (options) => {
      writeCandidateDb(
        options.dbPath,
        "usable.example",
        '[{"url":"https://usable.example/large.jpg","width":850,"height":480},{"url":"https://usable.example/small.jpg","width":280,"height":157}]',
        "https://usable.example/large.jpg"
      );
    },
    fetchImpl: (async (input: string | URL | Request) => {
      const url = String(input);
      requested.push(url);
      assert.match(url, /\/api\/v1\/videos\/uuid-1$/u, "smoke must never fetch an image asset URL");
      return new Response(JSON.stringify({
        thumbnails: [
          { fileUrl: "/small.jpg", width: 280, height: 157 },
          { fileUrl: "/large.jpg", width: 850, height: 480 }
        ]
      }), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch
  });

  assert.equal(report.valid_candidate_rows, 1);
  assert.equal(report.invalid_candidate_rows, 0);
  assert.equal(requested.length, 1);
  assert.ok(removed.includes(root));
});

test("runner treats successful legacy detail as SQL-NULL candidate state", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thumbnail-smoke-legacy-"));
  const report = await runLiveThumbnailSmoke({
    ...defaultLiveThumbnailSmokeOptions(), requiredHosts: 1, candidateLimit: 1
  }, {
    fetchRegistryHosts: async () => ["legacy.example"],
    makeTempDir: () => root,
    removeDir: (dir) => fs.rmSync(dir, { recursive: true, force: true }),
    crawlInstances: async () => undefined,
    crawlChannelsStage: async () => undefined,
    crawlCountsStage: async () => undefined,
    crawlVideosStage: async (options) => {
      writeCandidateDb(options.dbPath, "legacy.example", null, "https://legacy.example/legacy.jpg");
    },
    fetchImpl: (async () => new Response(JSON.stringify({ thumbnailPath: "/legacy.jpg" }), {
      status: 200, headers: { "content-type": "application/json" }
    })) as typeof fetch
  });
  assert.equal(report.invalid_candidate_rows, 0);
});

test("runner reports candidate mismatch and assertion rejects it", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thumbnail-smoke-mismatch-"));
  const report = await runLiveThumbnailSmoke({
    ...defaultLiveThumbnailSmokeOptions(), requiredHosts: 1, candidateLimit: 1
  }, {
    fetchRegistryHosts: async () => ["bad.example"],
    makeTempDir: () => root,
    removeDir: (dir) => fs.rmSync(dir, { recursive: true, force: true }),
    crawlInstances: async () => undefined,
    crawlChannelsStage: async () => undefined,
    crawlCountsStage: async () => undefined,
    crawlVideosStage: async (options) => {
      writeCandidateDb(options.dbPath, "bad.example", '[{"url":"https://bad.example/wrong.jpg","width":850,"height":480}]', "https://bad.example/wrong.jpg");
    },
    fetchImpl: (async () => new Response(JSON.stringify({
      thumbnails: [{ fileUrl: "/right.jpg", width: 850, height: 480 }]
    }), { status: 200 })) as typeof fetch
  });
  assert.equal(report.invalid_candidate_rows, 1);
  assert.throws(() => assertLiveThumbnailSmoke(report), /candidate persistence mismatches/);
});

test("runner cleans root artifacts when registry discovery fails", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thumbnail-smoke-failure-"));
  const removed: string[] = [];
  await assert.rejects(
    runLiveThumbnailSmoke(defaultLiveThumbnailSmokeOptions(), {
      fetchRegistryHosts: async () => { throw new Error("registry unavailable"); },
      makeTempDir: () => root,
      removeDir: (dir) => { removed.push(dir); fs.rmSync(dir, { recursive: true, force: true }); }
    }),
    /registry unavailable/
  );
  assert.deepEqual(removed, [root]);
});

test("report assertion rejects insufficient hosts and zero videos", () => {
  const base: LiveThumbnailSmokeReport = {
    started_at: "x", finished_at: "y", registry_url: "z",
    options: { required_hosts: 1 }, attempted_hosts: [], accepted_hosts: [], rejected_hosts: [], failures: [],
    selected_hosts: 0, crawled_hosts: 0, crawled_videos: 0,
    valid_candidate_rows: 0, invalid_candidate_rows: 0, artifact_root: null
  };
  assert.throws(() => assertLiveThumbnailSmoke(base), /insufficient usable hosts/);
  assert.throws(() => assertLiveThumbnailSmoke({ ...base, selected_hosts: 1, crawled_hosts: 1 }), /zero videos/);
});
