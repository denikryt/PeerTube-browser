/** Exercise the real fetch-to-curl fallback with an isolated fake curl command. */

import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";

const execFileAsync = promisify(execFile);
const httpModule = pathToFileURL(fileURLToPath(new URL("../../src/http.js", import.meta.url))).href;
const classificationModule = pathToFileURL(fileURLToPath(new URL("../../src/error-classification.js", import.meta.url))).href;

/** Run the actual retry loop in a child so the fake curl PATH cannot affect sibling tests. */
async function runCurlScenario(alwaysFail: boolean, maxRetries: number) {
  const directory = mkdtempSync(join(tmpdir(), "crawler-curl-retry-"));
  const attemptsFile = join(directory, "attempts");
  const curlPath = join(directory, "curl");
  const fakeCurl = `#!/bin/sh
attempts=0
if [ -f "$CURL_ATTEMPTS_FILE" ]; then attempts=$(cat "$CURL_ATTEMPTS_FILE"); fi
attempts=$((attempts + 1))
printf '%s' "$attempts" > "$CURL_ATTEMPTS_FILE"
if [ "$CURL_ALWAYS_FAIL" = 1 ] || [ "$attempts" -eq 1 ]; then
  printf 'curl: (7) Failed to connect to example.test port 443\\n' >&2
  exit 7
fi
printf '{"total":0,"data":[]}\\n__PEERTUBE_STATUS__=200'
`;
  writeFileSync(curlPath, fakeCurl);
  chmodSync(curlPath, 0o755);

  // Native fetch fails with a typed target connection refusal, forcing curl.
  const child = `
const { fetchJsonWithRetry } = await import(process.argv[1]);
const { classifyCrawlError } = await import(process.argv[2]);
globalThis.fetch = async () => {
  throw Object.assign(new Error("fetch failed"), { cause: { code: "ECONNREFUSED" } });
};
try {
  const value = await fetchJsonWithRetry("https://example.test/api/v1/video-channels?start=0&count=50", {
    timeoutMs: 1000, maxRetries: Number(process.argv[3])
  });
  process.stdout.write(JSON.stringify({ value }));
} catch (error) {
  process.stdout.write(JSON.stringify({ error: String(error), category: classifyCrawlError(error) }));
}
`;
  try {
    const { stdout } = await execFileAsync(process.execPath, [
      "--input-type=module", "-e", child, httpModule, classificationModule, String(maxRetries)
    ], {
      env: {
        ...process.env,
        PATH: `${directory}:${process.env.PATH ?? ""}`,
        CURL_ATTEMPTS_FILE: attemptsFile,
        CURL_ALWAYS_FAIL: alwaysFail ? "1" : "0"
      }
    });
    return { result: JSON.parse(stdout), attempts: Number(readFileSync(attemptsFile, "utf8")) };
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

test("curl exit 7 is retried and a later response completes the request", async () => {
  const observed = await runCurlScenario(false, 1);
  assert.equal(observed.attempts, 2);
  assert.deepEqual(observed.result, { value: { total: 0, data: [] } });
});

test("repeated curl exit 7 stays bounded and reports a host-local network error", async () => {
  const observed = await runCurlScenario(true, 1);
  assert.equal(observed.attempts, 2);
  assert.equal(observed.result.category.kind, "network");
  assert.equal(observed.result.category.retryable, true);
  assert.match(observed.result.error, /Failed to connect/);
});
