/** Report-only worker contracts over real staging SQLite and fake HTTP. */
import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import {
  VideoAvailabilityWorkStore,
  type AvailabilityWorkRow,
} from "../src/db/video-availability.js";
import { runAvailabilitySweep } from "../src/video-availability-worker.js";
import { NoNetworkError } from "../src/http.js";

/** Create exact updater-owned table without invoking crawler schema bootstrap. */
function fixture(rows: Array<[string, string, string]>) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "availability-"));
  const dbPath = path.join(dir, "stage.db");
  const db = new Database(dbPath);
  db.exec(`CREATE TABLE crawl_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    INSERT INTO crawl_state VALUES('video_corpus_role','updater_staging_delta');
    INSERT INTO crawl_state VALUES('video_availability_semantics','canonical_absence_atomic_ingest_v2');
    CREATE TABLE video_availability_work (
      video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, video_uuid TEXT NOT NULL,
      outcome TEXT CHECK (outcome IS NULL OR outcome IN ('available','not_found','gone','unknown')),
      checked_at INTEGER, error TEXT, PRIMARY KEY(video_id,instance_domain));
    CREATE INDEX idx_availability_work_host_identity ON video_availability_work
      (lower(trim(instance_domain)),video_id,instance_domain);
    CREATE TABLE videos(video_id TEXT,error_count INTEGER);
    INSERT INTO videos VALUES('canonical',17);`);
  const insert = db.prepare(
    "INSERT INTO video_availability_work(video_id,instance_domain,video_uuid) VALUES(?,?,?)",
  );
  db.transaction(() => rows.forEach((r) => insert.run(...r)))();
  db.close();
  return {
    dbPath,
    cleanup: () => fs.rmSync(dir, { recursive: true, force: true }),
  };
}
const options = {
  concurrency: 2,
  hostConcurrency: 2,
  hostDelayMs: 0,
  timeoutMs: 100,
  maxRetries: 0,
};

test("detail persistence failure is fatal and leaves evidence pending", async () => {
  const f = fixture([["a", "example.org", "uuid"]]), old = globalThis.fetch;
  const db = new Database(f.dbPath);
  db.exec("CREATE TRIGGER reject_detail BEFORE UPDATE ON video_availability_work " +
    "BEGIN SELECT RAISE(ABORT,'detail write failure'); END");
  db.close();
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    urls.push(String(input));
    return new Response(JSON.stringify({ uuid: "uuid" }));
  };
  try {
    await assert.rejects(runAvailabilitySweep({ dbPath: f.dbPath, ...options }), /detail write failure/);
    assert.deepEqual(urls.map(url => new URL(url).pathname), ["/api/v1/videos/uuid"]);
    const after = new Database(f.dbPath);
    assert.deepEqual(after.prepare("SELECT outcome,checked_at,error FROM video_availability_work").all(),
      [{ outcome: null, checked_at: null, error: null }]);
    after.close();
  } finally { globalThis.fetch = old; f.cleanup(); }
});

for (const status of [404, 410, 429, 503]) {
  test(`detail HTTP ${status} produces only per-video evidence, not a host skip`, async () => {
    const f = fixture([["a", "broken.org", "u-a"], ["b", "broken.org", "u-b"],
      ["c", "good.org", "u-c"]]);
    const old = globalThis.fetch, urls: string[] = [];
    globalThis.fetch = async (input) => {
      const url = new URL(String(input)); urls.push(String(url));
      if (url.host === "broken.org") return new Response("{}", { status });
      return new Response(JSON.stringify({ uuid: url.pathname.split("/").at(-1) }));
    };
    try {
      await runAvailabilitySweep({ dbPath: f.dbPath, ...options });
      assert.ok(urls.every(url => new URL(url).pathname.startsWith("/api/v1/videos/")));
      assert.equal(urls.filter(url => url.includes("broken.org")).length, 2);
      const db = new Database(f.dbPath);
      const expected = status === 404 ? "not_found" : status === 410 ? "gone" : "unknown";
      const broken = db.prepare("SELECT outcome,checked_at FROM video_availability_work " +
        "WHERE video_id IN ('a','b') ORDER BY video_id").all() as any[];
      assert.ok(broken.every(row => row.outcome === expected && Number.isSafeInteger(row.checked_at)));
      assert.equal((db.prepare("SELECT outcome FROM video_availability_work WHERE video_id='c'").get() as any).outcome, "available");
      assert.deepEqual(db.prepare("SELECT * FROM videos").all(), [{ video_id: "canonical", error_count: 17 }]);
      db.close();
    } finally { globalThis.fetch = old; f.cleanup(); }
  });
}

test("indexed full identity keyset processes every spelling exactly once in bounded batches", () => {
  const f = fixture(
    Array.from({ length: 1200 }, (_, i) => [
      String(Math.floor(i / 2)).padStart(5, "0"),
      i % 2 ? " Example.org " : "example.org",
      `uuid-${i}`,
    ]),
  );
  const store = new VideoAvailabilityWorkStore(f.dbPath);
  try {
    let cursor: { video_id: string; instance_domain: string } | undefined;
    const seen = new Set<string>();
    for (;;) {
      const batch = store.pendingBatch("example.org", cursor);
      if (!batch.length) break;
      assert.ok(batch.length <= 250);
      for (const row of batch) {
        const key = JSON.stringify([row.video_id, row.instance_domain]);
        assert.ok(!seen.has(key));
        seen.add(key);
        store.recordResult(row, {
          kind: "available",
          checkedAt: 123,
          protocol: "https:",
          detail: {},
        });
        assert.throws(() =>
          store.recordResult(row, { kind: "gone", checkedAt: 124 }),
        );
      }
      cursor = batch.at(-1)!;
    }
    assert.equal(seen.size, 1200);
    store.assertComplete();
    const db = new Database(f.dbPath, { readonly: true });
    const plan = db
      .prepare(
        `EXPLAIN QUERY PLAN SELECT video_id,instance_domain,video_uuid FROM video_availability_work
      WHERE lower(trim(instance_domain))=? AND outcome IS NULL AND (video_id,instance_domain)>(?,?)
      ORDER BY video_id,instance_domain LIMIT 250`,
      )
      .all("example.org", "0", "") as any[];
    assert.ok(
      plan.some((p) =>
        p.detail.includes("idx_availability_work_host_identity"),
      ),
    );
    assert.ok(!plan.some((p) => p.detail.includes("TEMP B-TREE")));
    db.close();
  } finally {
    store.close();
    f.cleanup();
  }
});

for (const mutation of [
  "UPDATE crawl_state SET value='standalone' WHERE key='video_corpus_role'",
  "DROP TABLE video_availability_work",
  "DROP INDEX idx_availability_work_host_identity",
  "UPDATE video_availability_work SET outcome='available',checked_at=1",
]) {
  test(`worker rejects nonpending or wrong-role corpus without mutation: ${mutation}`, () => {
    const f = fixture([["a", "example.org", "uuid"]]);
    const db = new Database(f.dbPath);
    db.exec(mutation);
    const before = db
      .prepare("SELECT sql FROM sqlite_master ORDER BY name")
      .all();
    db.close();
    try {
      assert.throws(() => new VideoAvailabilityWorkStore(f.dbPath));
      const after = new Database(f.dbPath);
      assert.deepEqual(
        after.prepare("SELECT sql FROM sqlite_master ORDER BY name").all(),
        before,
      );
      after.close();
    } finally {
      f.cleanup();
    }
  });
}

for (const [status, body, outcome] of [
  [200, { uuid: "uuid" }, "available"],
  [404, {}, "not_found"],
  [410, {}, "gone"],
  [200, { uuid: "wrong" }, "unknown"],
  [200, "<html>", "unknown"],
  [429, {}, "unknown"],
  [500, {}, "unknown"],
] as const) {
  test(`typed detail projection ${status}/${outcome} retains exact UUID and canonical state`, async () => {
    const f = fixture([["a", "example.org", "uuid"]]),
      old = globalThis.fetch;
    globalThis.fetch = async (input) =>
      String(input).includes("video-channels")
        ? new Response(JSON.stringify({ total: 0, data: [] }))
        : new Response(typeof body === "string" ? body : JSON.stringify(body), {
            status,
          });
    try {
      await runAvailabilitySweep({ dbPath: f.dbPath, ...options });
      const db = new Database(f.dbPath);
      const row = db
        .prepare("SELECT outcome,checked_at,error FROM video_availability_work")
        .get() as any;
      assert.equal(row.outcome, outcome);
      assert.ok(Number.isSafeInteger(row.checked_at));
      assert.equal(row.error === null, outcome !== "unknown");
      db.close();
    } finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
for (const fault of ["shape", "html", "target-reset", "unsafe"] as const) {
  test(`detail ${fault} cannot create host-wide unknown evidence`, async () => {
    const f = fixture([["a", fault === "unsafe" ? "user:secret@example.org" : "example.org", "uuid"]]);
    const old = globalThis.fetch, paths: string[] = [];
    globalThis.fetch = async (input) => {
      paths.push(String(input));
      if (fault === "target-reset") throw Object.assign(new Error("target reset"), { code: "ECONNRESET" });
      return new Response(fault === "html" ? "<html>" : JSON.stringify({ total: -1, data: [] }));
    };
    try {
      if (fault === "unsafe") {
        await assert.rejects(runAvailabilitySweep({ dbPath: f.dbPath, ...options }), /Unsafe availability work host/);
        assert.equal(paths.length, 0);
      } else {
        await runAvailabilitySweep({ dbPath: f.dbPath, ...options });
        // A transport reset may attempt the existing bounded protocol fallback;
        // none of those attempts may request a channel-wide preflight.
        assert.ok(paths.length >= 1);
        assert.ok(paths.every(url => new URL(url).pathname === "/api/v1/videos/uuid"));
      }
      const db = new Database(f.dbPath);
      const row = db.prepare("SELECT outcome,checked_at,error FROM video_availability_work").get() as any;
      assert.equal(row.outcome, fault === "unsafe" ? null : "unknown");
      assert.equal(row.checked_at === null, fault === "unsafe");
      if (row.error) assert.ok(!row.error.includes("secret"));
      db.close();
    } finally { globalThis.fetch = old; f.cleanup(); }
  });
}

test("direct video protocol fallback is independent of channel preflight", async () => {
  const f = fixture([["a", "example.org", "uuid"]]), old = globalThis.fetch;
  const urls: string[] = [];
  globalThis.fetch = async input => {
    const url = String(input); urls.push(url);
    if (url.startsWith("https:")) throw Object.assign(new Error("wrong TLS protocol"),
      { code: "ERR_SSL_WRONG_VERSION_NUMBER" });
    return new Response(JSON.stringify({ uuid: "uuid" }));
  };
  try {
    await runAvailabilitySweep({ dbPath: f.dbPath, ...options });
    assert.equal(urls.length, 2);
    assert.ok(urls[0].startsWith("https://") && urls[1].startsWith("http://"));
    assert.ok(urls.every(url => url.includes("/api/v1/videos/uuid")));
  } finally { globalThis.fetch = old; f.cleanup(); }
});

test("explicit local outage stops detail work without writing remote unknown", async () => {
  const f = fixture([["a", "example.org", "uuid"]]), old = globalThis.fetch;
  globalThis.fetch = async () => { throw new NoNetworkError("confirmed local outage"); };
  try {
    await assert.rejects(runAvailabilitySweep({ dbPath: f.dbPath, ...options }), /confirmed local outage/);
    const db = new Database(f.dbPath);
    assert.deepEqual(db.prepare("SELECT outcome,checked_at,error FROM video_availability_work").all(),
      [{ outcome: null, checked_at: null, error: null }]);
    db.close();
  } finally { globalThis.fetch = old; f.cleanup(); }
});

test("host and detail concurrency and start delay share one limiter", async () => {
  const f = fixture(
      Array.from({ length: 60 }, (_, i) => [
        String(i),
        `host${i % 3}.org`,
        `uuid-${i}`,
      ]),
    ),
    old = globalThis.fetch;
  const active = new Map<string, number>(),
    starts = new Map<string, number[]>();
  let maxHosts = 0;
  globalThis.fetch = async (input) => {
    const u = new URL(String(input)),
      host = u.host;
    active.set(host, (active.get(host) || 0) + 1);
    assert.ok(active.get(host)! <= 2);
    maxHosts = Math.max(
      maxHosts,
      [...active.values()].filter((n) => n > 0).length,
    );
    const times = starts.get(host) || [];
    times.push(Date.now());
    starts.set(host, times);
    await new Promise((r) => setTimeout(r, 12));
    active.set(host, active.get(host)! - 1);
    return new Response(
      JSON.stringify(
        u.pathname.includes("video-channels")
          ? { total: 0, data: [] }
          : { uuid: u.pathname.split("/").at(-1) },
      ),
    );
  };
  try {
    await runAvailabilitySweep({
      dbPath: f.dbPath,
      ...options,
      hostDelayMs: 5,
    });
    assert.ok(maxHosts <= 2);
    assert.ok(maxHosts > 1);
    for (const times of starts.values()) {
      // Twenty admitted details per host; the removed channel preflight must
      // not be counted as a request or reintroduced to satisfy this assertion.
      assert.equal(times.length, 20);
      for (let i = 1; i < times.length; i++)
        assert.ok(times[i] - times[i - 1] >= 4);
    }
  } finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});

test("SQLite result failure aborts instead of synthesizing unknown and closes after draining", async () => {
  const f = fixture([
      ["a", "example.org", "uuid"],
      ["b", "example.org", "uuid2"],
    ]),
    old = globalThis.fetch;
  const db = new Database(f.dbPath);
  db.exec(
    "CREATE TRIGGER reject_result BEFORE UPDATE ON video_availability_work BEGIN SELECT RAISE(ABORT,'disk write failure'); END",
  );
  db.close();
  globalThis.fetch = async (input) =>
    new Response(
      JSON.stringify(
        String(input).includes("video-channels")
          ? { total: 0, data: [] }
          : { uuid: String(input).split("/").at(-1) },
      ),
    );
  try {
    await assert.rejects(
      runAvailabilitySweep({ dbPath: f.dbPath, ...options }),
      /disk write failure/,
    );
    const after = new Database(f.dbPath);
    assert.equal(
      (
        after
          .prepare(
            "SELECT COUNT(*) AS n FROM video_availability_work WHERE outcome IS NULL",
          )
          .get() as any
      ).n,
      2,
    );
    after.close();
  } finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});

test("100k identity traversal remains bounded and index ordered", () => {
  const f = fixture(
    Array.from({ length: 100001 }, (_, i) => [
      String(i).padStart(6, "0"),
      i % 2 ? " Large.org " : "large.org",
      `uuid-${i}`,
    ]),
  );
  const store = new VideoAvailabilityWorkStore(f.dbPath);
  let count = 0,
    last = "";
  let cursor: AvailabilityWorkRow | undefined;
  try {
    for (;;) {
      const batch = store.pendingBatch("large.org", cursor);
      if (!batch.length) break;
      assert.ok(batch.length <= 250);
      for (const row of batch) {
        assert.ok(row.video_id > last);
        last = row.video_id;
        count++;
      }
      cursor = batch.at(-1)!;
    }
    assert.equal(count, 100001);
    assert.throws(() => store.assertComplete(), /incomplete/);
  } finally {
    store.close();
    f.cleanup();
  }
});

test("invalid results, unsafe diagnostic text and changed UUID cannot pass the write boundary", () => {
  const f = fixture([["a", "example.org", "uuid"]]);
  const store = new VideoAvailabilityWorkStore(f.dbPath);
  const row = {
    video_id: "a",
    instance_domain: "example.org",
    video_uuid: "uuid",
  };
  try {
    assert.throws(() =>
      store.recordResult(row, { kind: "gone", checkedAt: NaN }),
    );
    assert.throws(() =>
      store.recordResult(
        { ...row, video_uuid: "changed" },
        { kind: "gone", checkedAt: 1 },
      ),
    );
    assert.throws(() => store.assertComplete(), /incomplete/);
    assert.throws(
      () =>
        store.recordResult(row, {
          kind: "unknown",
          checkedAt: 1,
          error: {
            classification: { kind: "secret\nURL" },
            message: "",
            cause: null,
          },
        } as any),
      /diagnostic/,
    );
    assert.equal(store.pendingBatch("example.org").length, 1);
    store.recordResult(row, { kind: "unknown", checkedAt: 1,
      error: { classification: { kind: "network" }, message: "unavailable", cause: null }
    } as any);
    store.assertComplete();
  } finally {
    store.close();
    f.cleanup();
  }
});

for (const [key, value] of [
  ["concurrency", 0],
  ["hostConcurrency", 1.5],
  ["hostDelayMs", -1],
  ["timeoutMs", Infinity],
  ["maxRetries", NaN],
] as const) {
  test(`invalid network tuning ${key} fails before opening DB`, async () => {
    const f = fixture([]);
    const absent = path.join(path.dirname(f.dbPath), "absent.db");
    try {
      await assert.rejects(
        runAvailabilitySweep({ ...options, dbPath: absent, [key]: value }),
        /Invalid availability/,
      );
      assert.ok(!fs.existsSync(absent));
    } finally {
      f.cleanup();
    }
  });
}

/** An outage in one active host must halt another host's NEXT identity, not just the outer host queue. */
test("local outage stops new sibling host details and drains the already started detail", async () => {
  const f = fixture([
    ["a1", "a.test", "a-1"], ["a2", "a.test", "a-2"], ["a3", "a.test", "a-3"],
    ["b1", "b.test", "b-1"], ["b2", "b.test", "b-2"],
  ]);
  const previousFetch = globalThis.fetch;
  const requests: string[] = [];
  let outageRaised = false;
  let completedFirstA = false;
  let releaseA: (() => void) | undefined;
  const allowA = new Promise<void>(resolve => { releaseA = resolve; });
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    requests.push(`${url.hostname}/${url.pathname.split("/").at(-1)}`);
    if (url.hostname === "b.test") {
      outageRaised = true;
      // The sibling remains in flight until after the fatal rejection propagates.
      setTimeout(() => releaseA?.(), 10);
      throw new NoNetworkError("confirmed local outage");
    }
    await allowA;
    completedFirstA = true;
    assert.equal(outageRaised, true);
    return new Response(JSON.stringify({ uuid: url.pathname.split("/").at(-1) }));
  };
  try {
    await assert.rejects(runAvailabilitySweep({ ...options, dbPath: f.dbPath,
      concurrency: 2, hostConcurrency: 1 }), /confirmed local outage/);
    assert.deepEqual(requests.sort(), ["a.test/a-1", "b.test/b-1"]);
    assert.equal(completedFirstA, true);
    const db = new Database(f.dbPath, { readonly: true });
    assert.equal((db.prepare("SELECT outcome FROM video_availability_work WHERE video_id='a1'").get() as any).outcome, "available");
    assert.equal((db.prepare("SELECT count(*) n FROM video_availability_work WHERE outcome IS NULL").get() as any).n, 4);
    db.close();
  } finally { globalThis.fetch = previousFetch; f.cleanup(); }
});

test("one host's remote 404 does not stop another host's admitted details", async () => {
  const f = fixture([["a1", "a.test", "a-1"], ["a2", "a.test", "a-2"],
    ["b1", "b.test", "b-1"]]);
  const old = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async input => {
    const u = new URL(String(input));
    requests.push(`${u.hostname}/${u.pathname.split("/").at(-1)}`);
    return u.hostname === "b.test" ? new Response("{}", { status: 404 })
      : new Response(JSON.stringify({ uuid: u.pathname.split("/").at(-1) }));
  };
  try {
    await runAvailabilitySweep({ ...options, dbPath: f.dbPath, hostConcurrency: 1 });
    assert.deepEqual(requests.sort(), ["a.test/a-1", "a.test/a-2", "b.test/b-1"]);
    const db = new Database(f.dbPath, { readonly: true });
    assert.deepEqual(db.prepare("SELECT video_id,outcome FROM video_availability_work ORDER BY video_id").all(),
      [{video_id:"a1",outcome:"available"},{video_id:"a2",outcome:"available"},{video_id:"b1",outcome:"not_found"}]);
    db.close();
  } finally { globalThis.fetch = old; f.cleanup(); }
});

/** A process-local timeout cannot be erased by a successful alternate URL. */
test("availability leaves explicit local timeout pending and rejects the run", async () => {
  const f = fixture([["a", "example.org", "uuid"]]);
  const original = globalThis.fetch;
  const requests: string[] = [];
  const outage = new NoNetworkError("confirmed local timeout");
  globalThis.fetch = (async (input: string | URL | Request) => {
    requests.push(String(input));
    if (String(input).startsWith("https://")) throw outage;
    return new Response(JSON.stringify({ uuid: "uuid" }));
  }) as typeof fetch;
  try {
    await assert.rejects(runAvailabilitySweep({ dbPath: f.dbPath, ...options }),
      error => error === outage);
    assert.deepEqual(requests, ["https://example.org/api/v1/videos/uuid"]);
    const db = new Database(f.dbPath, { readonly: true });
    assert.deepEqual(db.prepare(
      "SELECT outcome,checked_at,error FROM video_availability_work WHERE video_id='a'"
    ).get(), { outcome: null, checked_at: null, error: null });
    db.close();
  } finally {
    globalThis.fetch = original;
    f.cleanup();
  }
});

test("availability keeps bounded fallback for ordinary remote timeout", async () => {
  const f = fixture([["a", "example.org", "uuid"]]);
  const original = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request) => {
    requests.push(String(input));
    if (String(input).startsWith("https://")) throw new Error("remote timeout");
    return new Response(JSON.stringify({ uuid: "uuid" }));
  }) as typeof fetch;
  try {
    await runAvailabilitySweep({ dbPath: f.dbPath, ...options });
    assert.deepEqual(requests, [
      "https://example.org/api/v1/videos/uuid",
      "http://example.org/api/v1/videos/uuid"
    ]);
    const db = new Database(f.dbPath, { readonly: true });
    const row = db.prepare("SELECT outcome,checked_at FROM video_availability_work WHERE video_id='a'").get() as {
      outcome: string; checked_at: number
    };
    assert.equal(row.outcome, "available");
    assert.ok(Number.isSafeInteger(row.checked_at));
    db.close();
  } finally {
    globalThis.fetch = original;
    f.cleanup();
  }
});
