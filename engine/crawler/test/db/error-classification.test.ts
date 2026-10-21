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
