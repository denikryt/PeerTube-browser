/** Regression coverage for persisted crawler error categories. */

import assert from "node:assert/strict";
import test from "node:test";

import {
  classifyCrawlError,
  formatCrawlError,
  shouldTryAlternateProtocol
} from "../../src/error-classification.js";

test("formatCrawlError stores useful categories without adding schema columns", () => {
  const timeout = new Error("This operation was aborted");
  timeout.name = "AbortError";

  assert.equal(formatCrawlError(timeout), "[timeout] This operation was aborted");
  assert.equal(formatCrawlError(new Error("HTTP 502 for https://example.test")), "[http_502] HTTP 502 for https://example.test");
  assert.equal(formatCrawlError(Object.assign(new Error("certificate has expired"), { code: "CERT_HAS_EXPIRED" })), "[tls] certificate has expired");
  assert.equal(formatCrawlError(new Error("unexpected payload")), "[unknown] unexpected payload");
});

test("error policy retries only transient failures and limits protocol fallback", () => {
  const timeout = new Error("This operation was aborted");
  timeout.name = "AbortError";
  const wrongProtocol = Object.assign(new Error("wrong version number"), {
    code: "ERR_SSL_WRONG_VERSION_NUMBER"
  });

  assert.equal(classifyCrawlError(new Error("HTTP 406 for https://example.test")).retryable, false);
  assert.equal(classifyCrawlError(new Error("HTTP 502 for https://example.test")).retryable, true);
  assert.equal(classifyCrawlError(new SyntaxError("Unexpected token")).retryable, false);
  assert.equal(shouldTryAlternateProtocol(new Error("HTTP 406 for https://example.test")), false);
  assert.equal(shouldTryAlternateProtocol(timeout), true);
  assert.equal(shouldTryAlternateProtocol(wrongProtocol), true);
});

test("structural HTTP status is authoritative while message parsing remains a fallback", () => {
  const structural = Object.assign(new Error("remote text says HTTP 404"), { status: 503 });
  const structuralResult = classifyCrawlError(structural);
  assert.deepEqual(structuralResult, {
    kind: "http_503",
    retryable: true,
    tryAlternateProtocol: false,
    httpStatus: 503
  });

  const structuralWithTransportText = Object.assign(new Error("timeout while reading HTTP response"), {
    status: 503
  });
  assert.deepEqual(classifyCrawlError(structuralWithTransportText), {
    kind: "http_503",
    retryable: true,
    tryAlternateProtocol: false,
    httpStatus: 503
  });

  const messageOnlyTimeout = new Error("timeout after text mentioning HTTP 503");
  assert.deepEqual(classifyCrawlError(messageOnlyTimeout), {
    kind: "timeout",
    retryable: true,
    tryAlternateProtocol: true,
    httpStatus: null
  });

  const fallback = classifyCrawlError(new Error("HTTP 410 for https://example.test"));
  assert.equal(fallback.httpStatus, 410);
  assert.equal(fallback.kind, "http_410");

  const malformedStructural = Object.assign(new Error("HTTP 429 for https://example.test"), {
    status: 42
  });
  assert.equal(classifyCrawlError(malformedStructural).httpStatus, 429);
});

test("JSON decoder syntax errors cannot synthesize HTTP absence from diagnostic text", () => {
  for (const status of [404, 410]) {
    const decoded = new SyntaxError(`Unexpected token while decoding HTTP ${status}`);
    assert.deepEqual(classifyCrawlError(decoded), {
      kind: "invalid_json",
      retryable: false,
      tryAlternateProtocol: false,
      httpStatus: null
    });
  }

  const actualHttp = Object.assign(new Error("HTTP 404 for https://example.test"), { status: 404 });
  assert.equal(classifyCrawlError(actualHttp).httpStatus, 404);
});
