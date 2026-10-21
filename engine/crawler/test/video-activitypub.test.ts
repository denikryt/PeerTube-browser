/** Security and identity tests for public ActivityPub live enrichment. */

import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import { buildCurlArgs, fetchJsonWithRetry } from "../src/http.js";
import {
  fetchActivityPubLiveMetadata,
  validateActivityPubCandidateUrl
} from "../src/video-activitypub.js";

test("candidate validation rejects foreign hosts, credentials, and non-http schemes", () => {
  assert.throws(
    () => validateActivityPubCandidateUrl("https://evil.example/videos/1", "video.example"),
    /host does not match/
  );
  assert.throws(
    () => validateActivityPubCandidateUrl("https://user:pass@video.example/videos/1", "video.example"),
    /credentials/
  );
  assert.throws(
    () => validateActivityPubCandidateUrl("file:///etc/passwd", "video.example"),
    /http or https/
  );
});



test("default REST HTTP behavior still follows redirects and uses JSON Accept", async () => {
  const args = buildCurlArgs("https://video.example/api/v1/videos/1", {
    timeoutMs: 1000,
    maxRetries: 0
  });
  assert.ok(args.includes("--location"));
  assert.ok(args.includes("accept: application/json"));

  const server = http.createServer((request, response) => {
    if (request.url === "/start") {
      response.writeHead(302, { location: "/target" });
      response.end();
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ ok: true }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    assert.deepEqual(
      await fetchJsonWithRetry(`http://127.0.0.1:${address.port}/start`, {
        timeoutMs: 1000,
        maxRetries: 0
      }),
      { ok: true }
    );
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve()))
    );
  }
});

test("curl fallback uses ActivityPub Accept header and does not follow redirects", () => {
  const args = buildCurlArgs("https://video.example/w/uuid", {
    timeoutMs: 1000,
    maxRetries: 0,
    accept: "application/activity+json",
    redirect: "error"
  });
  assert.ok(args.includes("accept: application/activity+json"));
  assert.equal(args.includes("--location"), false);
});

test("public ActivityPub Video accepts same-host identity and live metadata", async () => {
  const server = http.createServer((request, response) => {
    const host = request.headers.host;
    response.writeHead(200, { "content-type": "application/activity+json" });
    response.end(
      JSON.stringify({
        id: `http://${host}/w/uuid-1`,
        type: "Video",
        uuid: "uuid-1",
        permanentLive: true,
        liveSaveReplay: false
      })
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;
  try {
    assert.deepEqual(
      await fetchActivityPubLiveMetadata(`http://${host}/w/uuid-1`, host, "uuid-1", {
        timeoutMs: 1000,
        maxRetries: 0
      }),
      { permanentLive: true, liveSaveReplay: false }
    );
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve()))
    );
  }
});

test("ActivityPub redirect is rejected and the target origin is never requested", async () => {
  let targetRequests = 0;
  const target = http.createServer((_request, response) => {
    targetRequests += 1;
    response.writeHead(200, { "content-type": "application/activity+json" });
    response.end(JSON.stringify({ type: "Video" }));
  });
  await new Promise<void>((resolve) => target.listen(0, "127.0.0.1", resolve));
  const targetAddress = target.address();
  assert.ok(targetAddress && typeof targetAddress === "object");

  const source = http.createServer((_request, response) => {
    response.writeHead(302, {
      location: `http://127.0.0.1:${targetAddress.port}/redirected`
    });
    response.end();
  });
  await new Promise<void>((resolve) => source.listen(0, "127.0.0.1", resolve));
  const sourceAddress = source.address();
  assert.ok(sourceAddress && typeof sourceAddress === "object");
  const host = `127.0.0.1:${sourceAddress.port}`;

  try {
    await assert.rejects(
      fetchActivityPubLiveMetadata(`http://${host}/w/uuid-1`, host, "uuid-1", {
        timeoutMs: 1000,
        maxRetries: 0
      })
    );
    assert.equal(targetRequests, 0);
  } finally {
    await new Promise<void>((resolve, reject) =>
      source.close((error) => (error ? reject(error) : resolve()))
    );
    await new Promise<void>((resolve, reject) =>
      target.close((error) => (error ? reject(error) : resolve()))
    );
  }
});

test("ActivityPub response rejects wrong type, id, and UUID", async () => {
  async function run(payload: Record<string, unknown>, expected: RegExp) {
    const server = http.createServer((request, response) => {
      const host = request.headers.host;
      response.writeHead(200, { "content-type": "application/activity+json" });
      response.end(JSON.stringify({ id: `http://${host}/w/uuid-1`, ...payload }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    const host = `127.0.0.1:${address.port}`;
    try {
      await assert.rejects(
        fetchActivityPubLiveMetadata(`http://${host}/w/uuid-1`, host, "uuid-1", {
          timeoutMs: 1000,
          maxRetries: 0
        }),
        expected
      );
    } finally {
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve()))
      );
    }
  }

  await run({ type: "Note", uuid: "uuid-1" }, /not a Video/);
  await run({ type: "Video", id: "http://different.example/w/uuid-1", uuid: "uuid-1" }, /id does not match/);
  await run({ type: "Video", uuid: "different" }, /uuid does not match/);
});
