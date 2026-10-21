/** Scenario coverage for categorized instance health failures. */

import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";

import { ChannelStore } from "../../src/db/channels.js";
import { checkInstancesHealth, type InstanceHealthOptions } from "../../src/instances-health-cli.js";
import { NoNetworkError } from "../../src/http.js";
import { createTempDb, getRow } from "./helpers.js";

const execFileAsync = promisify(execFile);

test("instances health CLI stores the shared HTTP error category", async () => {
  const temp = createTempDb("crawler-instance-health-error-kind");
  let responseStatus = 502;
  const server = http.createServer((_request, response) => {
    response.writeHead(responseStatus, { "content-type": "application/json" });
    response.end(JSON.stringify(responseStatus === 200
      ? { total: 0, data: [] }
      : { error: "temporary upstream failure" }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const host = `127.0.0.1:${address.port}`;
  const store = new ChannelStore({ dbPath: temp.dbPath });
  store.markInstanceDone(host);
  store.close();

  try {
    const cliPath = fileURLToPath(
      new URL("../../src/instances-health-cli.js", import.meta.url)
    );
    const failed = await execFileAsync(process.execPath, [
      cliPath,
      "--db", temp.dbPath,
      "--host", host,
      "--timeout", "500",
      "--max-retries", "0"
    ]);
    const row = getRow<{ health_status: string; health_error: string }>(
      temp.dbPath,
      "SELECT health_status, health_error FROM instances WHERE host = ?",
      host
    );
    assert.equal(row.health_status, "error");
    assert.match(row.health_error, /^\[http_502\] HTTP 502 /);
    assert.ok(failed.stderr.includes(`error ${host} error=[http_502]`));

    responseStatus = 200;
    const healthy = await execFileAsync(process.execPath, [
      cliPath,
      "--db", temp.dbPath,
      "--host", host,
      "--timeout", "500",
      "--max-retries", "0"
    ]);
    assert.ok(healthy.stdout.includes(`ok ${host}`));
    assert.deepEqual(
      getRow<{ health_status: string; health_error: string | null }>(
        temp.dbPath,
        "SELECT health_status, health_error FROM instances WHERE host = ?",
        host
      ),
      { health_status: "ok", health_error: null }
    );
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => error ? reject(error) : resolve())
    );
    temp.cleanup();
  }
});

/** Probe one selected instance against an injected remote edge and inspect persisted health. */
async function probeWithResponse(
  error: Error,
  expectedRequests: string[],
  expectFatal: boolean
): Promise<void> {
  const temp = createTempDb("instance-protocol-fallback");
  const store = new ChannelStore({ dbPath: temp.dbPath });
  store.markInstanceDone("example.org");
  store.initializeParentEnumeration(["example.org"]);
  store.close();
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request) => {
    const url = String(input);
    requests.push(url);
    if (url.startsWith("https://")) throw error;
    return new Response(JSON.stringify({ total: 0, data: [] }), { status: 200 });
  }) as typeof fetch;
  const options: InstanceHealthOptions = {
    dbPath: temp.dbPath,
    hosts: ["example.org"],
    concurrency: 1,
    hostDelayMs: 0,
    timeoutMs: 50,
    maxRetries: 0,
    minAgeDays: null,
    minAgeMin: null,
    minAgeSec: null,
    hostsFile: null,
    host: null,
    errorsOnly: false
  };
  try {
    if (expectFatal) {
      await assert.rejects(checkInstancesHealth(options), rejected => rejected === error);
    } else {
      await checkInstancesHealth(options);
    }
    assert.deepEqual(requests, expectedRequests);
    assert.deepEqual(
      getRow<{ health_status: string | null; health_error: string | null }>(
        temp.dbPath,
        "SELECT health_status, health_error FROM instances WHERE host = ?",
        "example.org"
      ),
      expectFatal
        ? { health_status: null, health_error: null }
        : { health_status: "ok", health_error: null }
    );
  } finally {
    globalThis.fetch = originalFetch;
    temp.cleanup();
  }
}

test("instance probe propagates explicit local timeout without HTTP or ok write", async () => {
  await probeWithResponse(
    new NoNetworkError("confirmed local timeout"),
    ["https://example.org/api/v1/video-channels?start=0&count=1"],
    true
  );
});

test("instance probe retains alternate protocol for an ordinary remote timeout", async () => {
  await probeWithResponse(
    new Error("remote timeout"),
    [
      "https://example.org/api/v1/video-channels?start=0&count=1",
      "http://example.org/api/v1/video-channels?start=0&count=1"
    ],
    false
  );
});
