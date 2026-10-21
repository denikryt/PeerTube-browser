/** Regression tests for the canonical PeerTube video-detail request boundary. */

import assert from "node:assert/strict";
import test from "node:test";

import { fetchVideoDetailResult } from "../src/video-detail.js";
import { NoNetworkError } from "../src/http.js";
import type { RequestLimiter } from "../src/request-limiter.js";

const immediateLimiter: RequestLimiter = {
  async run<T>(operation: () => Promise<T>): Promise<T> {
    return operation();
  }
};

const options = { timeoutMs: 50, maxRetries: 0 };

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function withFetchStub(
  handler: (input: string | URL | Request) => Promise<Response>,
  fn: () => Promise<void>
): Promise<void> {
  const original = globalThis.fetch;
  globalThis.fetch = handler as typeof fetch;
  return fn().finally(() => {
    globalThis.fetch = original;
  });
}

test("matching UUID yields one available result and records the successful protocol", async () => {
  await withFetchStub(async () => response({ uuid: "video-a", name: "A" }), async () => {
    const result = await fetchVideoDetailResult<Record<string, unknown>>(
      "example.org",
      "video-a",
      options,
      "https:",
      immediateLimiter
    );

    assert.equal(result.kind, "available");
    if (result.kind === "available") {
      assert.equal(result.detail.uuid, "video-a");
      assert.equal(result.protocol, "https:");
      assert.equal(typeof result.checkedAt, "number");
    }
  });
});

test("direct final 404/410 become absence while other failures remain unknown", async () => {
  for (const [status, expected] of [[404, "not_found"], [410, "gone"]] as const) {
    await withFetchStub(async () => response({ error: "missing" }, status), async () => {
      const result = await fetchVideoDetailResult<Record<string, unknown>>(
        "example.org",
        "video-a",
        options,
        "https:",
        immediateLimiter
      );
      assert.equal(result.kind, expected);
    });
  }

  for (const status of [403, 408, 425, 429, 500, 503]) {
    await withFetchStub(async () => response({ error: "technical" }, status), async () => {
      const result = await fetchVideoDetailResult<Record<string, unknown>>(
        "example.org",
        "video-a",
        options,
        "https:",
        immediateLimiter
      );
      assert.equal(result.kind, "unknown");
    });
  }
});

test("semantic-invalid 2xx never becomes available or triggers protocol fallback", async () => {
  const invalidBodies: unknown[] = [
    null,
    "video-a",
    123,
    [],
    {},
    { uuid: null },
    { uuid: "" },
    { uuid: "video-b" },
    { uuid: "HTTP 404" }
  ];

  for (const body of invalidBodies) {
    let calls = 0;
    await withFetchStub(async () => {
      calls += 1;
      return response(body);
    }, async () => {
      const result = await fetchVideoDetailResult<Record<string, unknown>>(
        "example.org",
        "video-a",
        options,
        "https:",
        immediateLimiter
      );
      assert.equal(result.kind, "unknown");
      assert.equal(calls, 1);
      if (result.kind === "unknown") {
        assert.equal(result.error.classification.httpStatus, null);
        assert.ok(
          result.error.message === "invalid video detail payload" ||
          result.error.message === "invalid video detail identity"
        );
        assert.doesNotMatch(result.error.message, /HTTP 404|video-b/u);
      }
    });
  }
});

test("invalid JSON text containing HTTP 404/410 remains technical uncertainty", async () => {
  for (const text of ["HTTP 404", "HTTP 410"]) {
    let calls = 0;
    await withFetchStub(async () => {
      calls += 1;
      return new Response(text, {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    }, async () => {
      const result = await fetchVideoDetailResult<Record<string, unknown>>(
        "example.org",
        "video-a",
        options,
        "https:",
        immediateLimiter
      );
      assert.equal(result.kind, "unknown");
      assert.equal(calls, 1);
      if (result.kind === "unknown") {
        assert.equal(result.error.classification.kind, "invalid_json");
        assert.equal(result.error.classification.httpStatus, null);
      }
    });
  }
});

test("eligible transport failure may fall back once and returns the alternate success", async () => {
  const requests: string[] = [];
  await withFetchStub(async (input) => {
    const url = String(input);
    requests.push(url);
    if (url.startsWith("https://")) {
      const error = Object.assign(new Error("wrong version number"), {
        code: "ERR_SSL_WRONG_VERSION_NUMBER"
      });
      throw error;
    }
    return response({ uuid: "video-a", name: "alternate" });
  }, async () => {
    const result = await fetchVideoDetailResult<Record<string, unknown>>(
      "example.org",
      "video-a",
      options,
      "https:",
      immediateLimiter
    );
    assert.equal(result.kind, "available");
    if (result.kind === "available") assert.equal(result.protocol, "http:");
    assert.deepEqual(requests, [
      "https://example.org/api/v1/videos/video-a",
      "http://example.org/api/v1/videos/video-a"
    ]);
  });
});

test("eligible fallback exhaustion returns one unknown without a caller retry loop", async () => {
  const requests: string[] = [];
  await withFetchStub(async (input) => {
    const url = String(input);
    requests.push(url);
    if (url.startsWith("https://")) {
      throw Object.assign(new Error("wrong version number"), {
        code: "ERR_SSL_WRONG_VERSION_NUMBER"
      });
    }
    // This terminal TLS failure does not invoke native-fetch-to-curl or retry.
    // The test isolates one exhausted HTTPS-to-HTTP protocol fallback.
    throw Object.assign(new Error("certificate mismatch"), {
      code: "ERR_TLS_CERT_ALTNAME_INVALID"
    });
  }, async () => {
    const result = await fetchVideoDetailResult<Record<string, unknown>>(
      "example.org",
      "video-a",
      options,
      "https:",
      immediateLimiter
    );
    assert.equal(result.kind, "unknown");
    assert.deepEqual(requests, [
      "https://example.org/api/v1/videos/video-a",
      "http://example.org/api/v1/videos/video-a"
    ]);
  });
});

test("wrong identity with HTTP-like text remains unknown, not absent", async () => {
  await withFetchStub(async () => response({ uuid: "video-b", note: "HTTP 410" }), async () => {
    const result = await fetchVideoDetailResult<Record<string, unknown>>(
      "example.org", "video-a", options, "https:", immediateLimiter
    );
    assert.equal(result.kind, "unknown");
  });
});

/** A confirmed process-local outage is fatal before choosing another protocol. */
test("explicit local timeout cannot be turned into available by HTTP fallback", async () => {
  const requests: string[] = [];
  const failure = new NoNetworkError("confirmed local timeout");
  await withFetchStub(async (input) => {
    requests.push(String(input));
    if (String(input).startsWith("https://")) throw failure;
    return response({ uuid: "video-a", name: "not-authoritative" });
  }, async () => {
    await assert.rejects(
      fetchVideoDetailResult<Record<string, unknown>>(
        "example.org", "video-a", options, "https:", immediateLimiter
      ),
      error => error === failure
    );
  });
  assert.deepEqual(requests, ["https://example.org/api/v1/videos/video-a"]);
});

/** A target-specific timeout is not evidence of a process-local outage. */
test("ordinary remote timeout still permits bounded HTTP fallback", async () => {
  const requests: string[] = [];
  await withFetchStub(async (input) => {
    requests.push(String(input));
    if (String(input).startsWith("https://")) throw new Error("remote timeout");
    return response({ uuid: "video-a" });
  }, async () => {
    const result = await fetchVideoDetailResult<Record<string, unknown>>(
      "example.org", "video-a", options, "https:", immediateLimiter
    );
    assert.equal(result.kind, "available");
    if (result.kind === "available") assert.equal(result.protocol, "http:");
  });
  assert.deepEqual(requests, [
    "https://example.org/api/v1/videos/video-a",
    "http://example.org/api/v1/videos/video-a"
  ]);
});
