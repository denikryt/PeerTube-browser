/** Scoped discovery no-op is explicit and never suppresses malformed registry. */
import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { spawnSync } from "node:child_process";
import { crawl } from "../src/crawler.js";
import type { CrawlOptions } from "../src/types.js";

/** Resumed no-graph fixture ensures no progress is fabricated by discovery. */
function fixture(): {
  dir: string;
  options: CrawlOptions;
  cleanup: () => void;
} {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "registry-scope-"));
  const hosts = path.join(dir, "hosts");
  fs.writeFileSync(hosts, "delisted.org\n");
  const dbPath = path.join(dir, "stage.db");
  const db = new Database(dbPath);
  db.exec("CREATE TABLE crawl_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)");
  db.close();
  return {
    dir,
    options: {
      dbPath,
      whitelistUrl: "https://registry.org",
      whitelistFile: null,
      hostsFile: hosts,
      excludeHostsFile: null,
      concurrency: 1,
      hostDelayMs: 0,
      timeoutMs: 10,
      maxRetries: 0,
      maxErrors: 0,
      maxInstances: 0,
      resume: true,
      collectGraph: false,
      expandBeyondWhitelist: false,
      allowEmptyScopedWhitelist: true,
    },
    cleanup: () => fs.rmSync(dir, { recursive: true, force: true }),
  };
}
for (const payload of [[], { data: [] }, ["registry.org"]]) {
  test(`scoped opt-in closes successful empty discovery without stamps: ${JSON.stringify(payload)}`, async () => {
    const f = fixture(),
      old = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify(payload));
    try {
      await crawl(f.options);
      const db = new Database(f.options.dbPath);
      assert.equal(
        (db.prepare("SELECT COUNT(*) AS n FROM instances").get() as any).n,
        0,
      );
      assert.deepEqual(db.prepare("SELECT * FROM crawl_state").all(), []);
      assert.deepEqual(
        db
          .prepare(
            "SELECT name FROM sqlite_master WHERE name IN ('queue','edges')",
          )
          .all(),
        [],
      );
      db.close();
    } finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
for (const payload of [
  [],
  { data: [] },
  ["registry.org"],
  {},
  [null],
  { data: [{ nope: true }] },
]) {
  test(`default discovery or corrupt registry remains fatal: ${JSON.stringify(payload)}`, async () => {
    const f = fixture(),
      old = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify(payload));
    try {
      await assert.rejects(
        crawl({ ...f.options, allowEmptyScopedWhitelist: false }),
      );
      if (
        [
          JSON.stringify({}),
          JSON.stringify([null]),
          JSON.stringify({ data: [{ nope: true }] }),
        ].includes(JSON.stringify(payload))
      ) {
        await assert.rejects(crawl(f.options));
      }
    } finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
for (const misuse of [
  { resume: false },
  { collectGraph: true },
  { expandBeyondWhitelist: true },
  { hostsFile: null },
]) {
  test(`direct opt-in misuse rejects before corpus reset: ${JSON.stringify(misuse)}`, async () => {
    const f = fixture();
    try {
      await assert.rejects(crawl({ ...f.options, ...misuse }), /requires/);
      const db = new Database(f.options.dbPath);
      assert.deepEqual(
        db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all(),
        [{ name: "crawl_state" }],
      );
      db.close();
    } finally {
      f.cleanup();
    }
  });
}

test("sweep CLI rejects all ordinary selectors before touching a typo DB", () => {
  const f = fixture();
  const cli = path.resolve("dist/videos-cli.js");
  try {
    for (const extra of [
      "--new-videos",
      "--tags",
      "--update-tags",
      "--comments",
      "--refresh-thumbnails",
      "--metadata",
      "--update-metadata",
      "--errors",
      "--resume",
      "--only-healthy-hosts",
      "--hosts-file=x",
      "--exclude-hosts-file=x",
      "--existing-db=x",
      "--sort=x",
      "--max-instances=1",
      "--max-channels=1",
      "--max-videos-pages=1",
      "--stop-after-full-pages=1",
    ]) {
      const typo = path.join(f.dir, "missing.db");
      const r = spawnSync(
        process.execPath,
        [cli, "--db", typo, "--check-availability", extra],
        { encoding: "utf8" },
      );
      assert.notEqual(r.status, 0, extra);
      assert.match(r.stderr, /cannot combine/, extra);
      assert.ok(!fs.existsSync(typo));
    }
  } finally {
    f.cleanup();
  }
});

test("direct scoped discovery freezes include before registry await", async () => {
  const f = fixture(),
    old = globalThis.fetch;
  globalThis.fetch = async () => {
    fs.writeFileSync(f.options.hostsFile!, "# now empty\n");
    return new Response(JSON.stringify(["registry.org"]));
  };
  try {
    await crawl(f.options);
    const db = new Database(f.options.dbPath);
    assert.deepEqual(db.prepare("SELECT host FROM instances").all(), []);
    db.close();
  } finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});

test("denylist-only scoped intersection is successful zero discovery", async () => {
  const f = fixture(),
    old = globalThis.fetch;
  const deny = path.join(f.dir, "denied");
  fs.writeFileSync(deny, "delisted.org");
  globalThis.fetch = async () => new Response(JSON.stringify(["delisted.org"]));
  try {
    await crawl({ ...f.options, excludeHostsFile: deny });
    const db = new Database(f.options.dbPath);
    assert.deepEqual(db.prepare("SELECT host FROM instances").all(), []);
    db.close();
  } finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});

test("corrupt DB and missing/empty scoped file are fatal before registry HTTP", async () => {
  const f = fixture(),
    old = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => {
    requests++;
    return new Response("[]");
  };
  try {
    fs.writeFileSync(f.options.hostsFile!, "# empty");
    await assert.rejects(crawl(f.options), /requires/);
    fs.unlinkSync(f.options.hostsFile!);
    await assert.rejects(crawl(f.options));
    fs.writeFileSync(f.options.hostsFile!, "delisted.org");
    fs.writeFileSync(f.options.dbPath, "corrupt");
    await assert.rejects(crawl(f.options));
    assert.equal(requests, 0);
  } finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});

test("direct opt-in rejects nonboolean permission before DB initialization", async () => {
  const f = fixture();
  try {
    await assert.rejects(
      crawl({ ...f.options, allowEmptyScopedWhitelist: "true" } as any),
      /must be boolean/,
    );
    const db = new Database(f.options.dbPath);
    assert.deepEqual(
      db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all(),
      [{ name: "crawl_state" }],
    );
    db.close();
  } finally {
    f.cleanup();
  }
});
