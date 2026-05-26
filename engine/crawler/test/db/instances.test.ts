/**
 * Characterization tests for instance crawler database persistence.
 */

import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";

import { CrawlerStore } from "../../src/db.js";
import { allRows, createTempDb, getRow } from "./helpers.js";

test("CrawlerStore resume=false resets the database and creates graph state conditionally", () => {
  const temp = createTempDb("crawler-instances-reset");
  try {
    fs.writeFileSync(temp.dbPath, "old data");
    const store = new CrawlerStore({
      dbPath: temp.dbPath,
      resume: false,
      collectGraph: true,
      expandBeyondWhitelist: true
    });
    store.close();

    const tables = allRows<{ name: string }>(
      temp.dbPath,
      "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).map((row) => row.name);
    assert.ok(tables.includes("instances"));
    assert.ok(tables.includes("edges"));
    assert.ok(tables.includes("queue"));
    assert.ok(tables.includes("crawl_state"));
  } finally {
    temp.cleanup();
  }
});

test("CrawlerStore without graph options keeps graph-only tables absent", () => {
  const temp = createTempDb("crawler-instances-no-graph");
  try {
    const store = new CrawlerStore({
      dbPath: temp.dbPath,
      resume: false,
      collectGraph: false,
      expandBeyondWhitelist: false
    });
    store.close();

    const tables = allRows<{ name: string }>(
      temp.dbPath,
      "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).map((row) => row.name);
    assert.ok(!tables.includes("edges"));
    assert.ok(!tables.includes("queue"));
    assert.ok(!tables.includes("crawl_state"));
  } finally {
    temp.cleanup();
  }
});

test("CrawlerStore queue, progress, errors, edges, and recovery keep current DB effects", () => {
  const temp = createTempDb("crawler-instances-progress");
  try {
    const store = new CrawlerStore({
      dbPath: temp.dbPath,
      resume: false,
      collectGraph: true,
      expandBeyondWhitelist: true
    });

    store.ensureInstance("example.org");
    store.enqueueHost("example.org");
    assert.equal(store.claimNextHost(), "example.org");
    assert.equal(
      getRow<{ status: string }>(
        temp.dbPath,
        "SELECT status FROM instance_crawl_progress WHERE host = ?",
        "example.org"
      ).status,
      "processing"
    );

    store.markError("example.org", "boom");
    assert.deepEqual(
      getRow<{ last_error: string; last_error_source: string }>(
        temp.dbPath,
        "SELECT last_error, last_error_source FROM instances WHERE host = ?",
        "example.org"
      ),
      { last_error: "boom", last_error_source: "instances" }
    );
    assert.equal(store.getErrorCount("example.org"), 1);

    store.markDone("example.org");
    assert.equal(
      getRow<{ last_error: string | null; status: string }>(
        temp.dbPath,
        `SELECT i.last_error, p.status
         FROM instances i JOIN instance_crawl_progress p ON p.host = i.host
         WHERE i.host = ?`,
        "example.org"
      ).status,
      "done"
    );

    store.insertEdge("example.org", "example.org");
    store.insertEdge("example.org", "peer.example");
    store.insertEdge("example.org", "peer.example");
    assert.equal(
      allRows(temp.dbPath, "SELECT * FROM edges WHERE source_host = ?", "example.org").length,
      1
    );

    store.ensureInstance("pending.example");
    store.enqueueHost("pending.example");
    assert.equal(store.claimNextHost(), "pending.example");
    store.recoverQueue(new Set(["pending.example"]));
    assert.equal(
      getRow<{ status: string }>(
        temp.dbPath,
        "SELECT status FROM instance_crawl_progress WHERE host = ?",
        "pending.example"
      ).status,
      "pending"
    );
    store.close();
  } finally {
    temp.cleanup();
  }
});
