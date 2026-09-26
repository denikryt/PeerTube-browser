/** Deterministic tests for live-thumbnail smoke validation and orchestration. */

import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import Database from "better-sqlite3";
import {
  assertLiveThumbnailSmoke,
  defaultLiveThumbnailSmokeOptions,
  diagnoseFailedThumbnail,
  probeThumbnailUrl,
  runLiveThumbnailSmoke,
  type LiveThumbnailSmokeReport
} from "../../src/live-thumbnail-smoke.js";

async function withServer(
  handler: http.RequestListener,
  run: (baseUrl: string) => Promise<void>
): Promise<void> {
  const server = http.createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

test("thumbnail probe requires 2xx image content and non-empty bounded body", async () => {
  await withServer((request, response) => {
    if (request.url === "/redirect") {
      response.writeHead(302, { location: "/image" }).end();
      return;
    }
    if (request.url === "/image") {
      response.writeHead(200, { "content-type": "image/webp" }).end(Buffer.alloc(100_000, 1));
      return;
    }
    if (request.url === "/html") {
      response.writeHead(200, { "content-type": "text/html" }).end("not an image");
      return;
    }
    if (request.url === "/empty") {
      response.writeHead(200, { "content-type": "image/jpeg" }).end();
      return;
    }
    response.writeHead(404, { "content-type": "image/jpeg" }).end("missing");
  }, async (baseUrl) => {
    const valid = await probeThumbnailUrl(`${baseUrl}/redirect`, { timeoutMs: 1000, bodyCapBytes: 64 });
    assert.equal(valid.valid, true);
    assert.equal(valid.contentType, "image/webp");
    assert.equal(valid.bytesRead, 64);
    assert.match(valid.finalUrl ?? "", /\/image$/);

    assert.equal((await probeThumbnailUrl(`${baseUrl}/missing`, { timeoutMs: 1000 })).valid, false);
    assert.equal((await probeThumbnailUrl(`${baseUrl}/html`, { timeoutMs: 1000 })).error, "unexpected content-type text/html");
    assert.equal((await probeThumbnailUrl(`${baseUrl}/empty`, { timeoutMs: 1000 })).error, "empty response body");
  });
});

test("thumbnail probe returns controlled timeout/network failures", async () => {
  const result = await probeThumbnailUrl("https://unreachable.invalid/image.jpg", {
    timeoutMs: 10,
    fetchImpl: async () => { throw new Error("network unavailable"); }
  });
  assert.equal(result.valid, false);
  assert.equal(result.error, "network unavailable");
});

test("detail diagnostics classify working fallback, missing fields, and unavailable detail", async () => {
  const row = {
    video_id: "video-1",
    video_uuid: "uuid-1",
    instance_domain: "example.test",
    thumbnail_url: "https://example.test/stale.jpg",
    preview_path: "/preview.jpg"
  };
  const calls: string[] = [];
  const workingFetch = async (input: string | URL | Request) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/api/v1/videos/")) {
      return new Response(JSON.stringify({ previewPath: "/works.jpg", previewUrl: "/works.jpg" }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    }
    return new Response("x", { status: 200, headers: { "content-type": "image/jpeg" } });
  };
  const working = await diagnoseFailedThumbnail(row, { timeoutMs: 1000, fetchImpl: workingFetch as typeof fetch });
  assert.equal(working.classification, "stored_thumbnail_stale_but_live_candidate_works");
  assert.equal(working.candidateProbes.length, 1, "duplicate resolved candidates must be probed once");

  const missing = await diagnoseFailedThumbnail(row, {
    timeoutMs: 1000,
    fetchImpl: (async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } })) as typeof fetch
  });
  assert.equal(missing.classification, "media_fields_missing");

  const unavailable = await diagnoseFailedThumbnail(row, {
    timeoutMs: 1000,
    fetchImpl: (async () => new Response("no", { status: 503 })) as typeof fetch
  });
  assert.equal(unavailable.classification, "video_detail_unavailable");
});

test("detail diagnostics classify all invalid live candidates", async () => {
  const result = await diagnoseFailedThumbnail({
    video_id: "video-1",
    video_uuid: "uuid-1",
    instance_domain: "example.test",
    thumbnail_url: "https://example.test/stale.jpg",
    preview_path: null
  }, {
    timeoutMs: 1000,
    fetchImpl: (async (input: string | URL | Request) => {
      if (String(input).includes("/api/v1/videos/")) {
        return new Response(JSON.stringify({ thumbnailPath: "/still-broken.jpg" }), { status: 200 });
      }
      return new Response("missing", { status: 404, headers: { "content-type": "image/jpeg" } });
    }) as typeof fetch
  });
  assert.equal(result.classification, "all_live_candidates_invalid");
});

test("runner uses isolated production-stage dependencies and cleans artifacts", async () => {
  const removed: string[] = [];
  const createdRoot = fs.mkdtempSync(path.join(os.tmpdir(), "thumbnail-smoke-unit-"));
  const options = {
    ...defaultLiveThumbnailSmokeOptions(),
    requiredHosts: 1,
    candidateLimit: 2,
    keepArtifacts: false
  };
  const report = await runLiveThumbnailSmoke(options, {
    fetchRegistryHosts: async () => ["empty.example", "usable.example"],
    makeTempDir: () => createdRoot,
    removeDir: (dir) => {
      removed.push(dir);
      fs.rmSync(dir, { recursive: true, force: true });
    },
    crawlInstances: async () => undefined,
    crawlChannelsStage: async () => undefined,
    crawlCountsStage: async () => undefined,
    crawlVideosStage: async (crawlOptions) => {
      const db = new Database(crawlOptions.dbPath);
      db.exec(`CREATE TABLE IF NOT EXISTS videos (
        video_id TEXT, video_uuid TEXT, instance_domain TEXT,
        thumbnail_url TEXT, preview_path TEXT
      )`);
      if (crawlOptions.dbPath.includes("usable.example")) {
        db.prepare("INSERT INTO videos VALUES (?, ?, ?, ?, ?)").run(
          "video-1", "uuid-1", "usable.example", "https://usable.example/thumb.jpg", "/preview.jpg"
        );
      }
      db.close();
    },
    fetchImpl: (async () => new Response("x", { status: 200, headers: { "content-type": "image/jpeg" } })) as typeof fetch
  });

  assert.equal(report.selected_hosts, 1);
  assert.equal(report.crawled_videos, 1);
  assert.equal(report.invalid_thumbnails, 0);
  assert.deepEqual(report.attempted_hosts, ["empty.example", "usable.example"]);
  assert.ok(removed.includes(createdRoot), "root artifact directory must be cleaned in finally");
});

test("runner cleans the root artifact directory when registry discovery fails", async () => {
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

test("runner preserves artifacts when requested", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thumbnail-smoke-keep-"));
  try {
    const report = await runLiveThumbnailSmoke({
      ...defaultLiveThumbnailSmokeOptions(), requiredHosts: 1, candidateLimit: 1, keepArtifacts: true
    }, {
      fetchRegistryHosts: async () => ["usable.example"],
      makeTempDir: () => root,
      removeDir: () => { throw new Error("keep-artifacts must not remove directories"); },
      crawlInstances: async () => undefined,
      crawlChannelsStage: async () => undefined,
      crawlCountsStage: async () => undefined,
      crawlVideosStage: async (crawlOptions) => {
        const db = new Database(crawlOptions.dbPath);
        db.exec("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, thumbnail_url TEXT, preview_path TEXT)");
        db.prepare("INSERT INTO videos VALUES (?, ?, ?, ?, ?)").run("v", "u", "usable.example", "https://usable.example/t.jpg", null);
        db.close();
      },
      fetchImpl: (async () => new Response("x", { status: 200, headers: { "content-type": "image/jpeg" } })) as typeof fetch
    });
    assert.equal(report.artifact_root, root);
    assert.equal(fs.existsSync(root), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("report assertion rejects insufficient hosts, zero videos, and invalid thumbnails", () => {
  const base: LiveThumbnailSmokeReport = {
    started_at: "x", finished_at: "y", registry_url: "z",
    options: { required_hosts: 1 }, attempted_hosts: [], accepted_hosts: [], rejected_hosts: [], failures: [],
    selected_hosts: 0, crawled_hosts: 0, crawled_videos: 0,
    valid_thumbnails: 0, invalid_thumbnails: 0, artifact_root: null
  };
  assert.throws(() => assertLiveThumbnailSmoke(base), /insufficient usable hosts/);
  assert.throws(() => assertLiveThumbnailSmoke({ ...base, selected_hosts: 1, crawled_hosts: 1 }), /zero videos/);
  assert.throws(() => assertLiveThumbnailSmoke({
    ...base, selected_hosts: 1, crawled_hosts: 1, crawled_videos: 1, invalid_thumbnails: 1
  }), /invalid thumbnails/);
});
