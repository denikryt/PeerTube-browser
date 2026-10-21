/** Deterministic tests for crawler host include/exclude scoping helpers. */

import assert from "node:assert/strict";
import test from "node:test";
import { includeHosts, normalizeHostToken, scopeHosts } from "../../src/host-filters.js";

test("includeHosts keeps only explicit scoped hosts", () => {
  assert.deepEqual(
    includeHosts(["alpha.example", "beta.example"], new Set(["beta.example"])),
    ["beta.example"]
  );
});

test("scopeHosts applies include filters before excludes", () => {
  assert.deepEqual(
    scopeHosts(
      ["alpha.example", "beta.example", "gamma.example"],
      new Set(["beta.example", "gamma.example"]),
      new Set(["gamma.example"])
    ),
    ["beta.example"]
  );
});

test("normalizeHostToken accepts urls and path-like values from host lists", () => {
  assert.equal(normalizeHostToken("https://Example.test/path"), "example.test");
  assert.equal(normalizeHostToken("example.test/channel"), "example.test");
  assert.equal(normalizeHostToken("  beta.example  "), "beta.example");
});
