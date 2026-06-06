/** Deterministic coverage for shared JoinPeerTube registry parsing. */

import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { fetchInstanceRegistryHosts, parseInstanceRegistryHosts } from "../../src/instance-registry.js";

test("registry parser preserves order, normalizes hosts, and removes duplicates", () => {
  assert.deepEqual(
    parseInstanceRegistryHosts({
      data: [
        { host: "HTTPS://Example.org/" },
        "second.example",
        { host: "example.org" },
        { nope: "ignored" },
        ""
      ]
    }),
    ["example.org", "second.example"]
  );
});

test("registry parser accepts top-level arrays and rejects unusable payloads", () => {
  assert.deepEqual(parseInstanceRegistryHosts(["one.example", 123]), ["one.example", "123"]);
  assert.throws(() => parseInstanceRegistryHosts({ data: [{ nope: true }] }), /no hosts/);
  assert.throws(() => parseInstanceRegistryHosts({}), /Unexpected whitelist JSON shape/);
});


test("registry fetch preserves retry behavior before parsing normalized hosts", async () => {
  let requests = 0;
  const server = http.createServer((_request, response) => {
    requests += 1;
    if (requests === 1) {
      response.writeHead(500, { "content-type": "application/json" }).end("{}");
      return;
    }
    response.writeHead(200, { "content-type": "application/json" }).end(
      JSON.stringify({ data: [{ host: "Retry.Example" }] })
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    const hosts = await fetchInstanceRegistryHosts(
      `http://127.0.0.1:${address.port}/instances`,
      { timeoutMs: 1000, maxRetries: 1 }
    );
    assert.deepEqual(hosts, ["retry.example"]);
    assert.equal(requests, 2);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => error ? reject(error) : resolve())
    );
  }
});
