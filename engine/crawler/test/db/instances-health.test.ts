/** Scenario coverage for categorized instance health failures. */

import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";

import { ChannelStore } from "../../src/db/channels.js";
import { createTempDb, getRow } from "./helpers.js";

const execFileAsync = promisify(execFile);

test("instances health CLI stores the shared HTTP error category", async () => {
  const temp = createTempDb("crawler-instance-health-error-kind");
  let responseStatus = 502;
  const server = http.createServer((_request, response) => {
    response.writeHead(responseStatus, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: "temporary upstream failure" }));
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
