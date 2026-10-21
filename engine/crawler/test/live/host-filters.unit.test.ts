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

test("omitted include is unrestricted while explicit empty include selects zero",()=>{
 assert.deepEqual(includeHosts(['a.example','b.example'],null),['a.example','b.example']);
 assert.deepEqual(includeHosts(['a.example','b.example'],new Set()),[]);
});

test("internal host selection intersects operator includes and exclusions",()=>{
 assert.deepEqual(scopeHosts(['a.example','b.example'],new Set(['b.example']),new Set(),['a.example']),[]);
 assert.deepEqual(scopeHosts(['a.example','b.example'],null,new Set(),[]),[]);
 assert.deepEqual(scopeHosts(['a.example','b.example'],new Set(['a.example']),new Set(),['a.example']),['a.example']);
});
