/** Regression scenarios for field-observed channel completion and host scope defects. */
import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { crawlChannels, checkChannelHealth, type ChannelCrawlOptions } from "../../src/channels-worker.js";
import { NoNetworkError, isNoNetworkError } from "../../src/http.js";
import { checkInstancesHealth } from "../../src/instances-health-cli.js";
import { crawlChannelVideosCount } from "../../src/channels-videos-count-worker.js";
import { crawlVideos, type VideoCrawlOptions } from "../../src/videos-worker.js";
import { crawlHostPipeline } from "../../src/host-pipeline-worker.js";
import { spawnSync } from "node:child_process";
import { ChannelStore } from "../../src/db/channels.js";
import { VideoStore } from "../../src/db/videos.js";
import { createTempDb } from "./helpers.js";
/** Seed independent parent rows; replace only the remote API boundary in tests. */
function fixture() {
  const temp = createTempDb("parent-lifecycle-regression"), store = new ChannelStore({ dbPath: temp.dbPath });
  for (const host of ["a.example", "b.example"]) {
    store.markInstanceHealthOk(host);
    store.upsertChannels([{ channelId: "old", channelName: "old", channelUrl: null, displayName: "canonical", instanceDomain: host, videosCount: null, followersCount: 0, avatarUrl: null }]);
  }
  store.close();
  const options: ChannelCrawlOptions = { dbPath: temp.dbPath, hostsFile: null, excludeHostsFile: null, concurrency: 1, hostConcurrency: 1, hostDelayMs: 0, timeoutMs: 1000, maxRetries: 0, newOnly: false, maxInstances: 0, maxChannels: 0, resume: false, errorsOnly: false };
  return { ...temp, options };
}

/** Seed a prepared fresh instance for a test of channel enumeration itself.
 * Standalone enumeration probes first; these cases instead exercise the
 * Updater-owned already-initialized branch, with real persisted provenance.
 */
function prepareListing(dbPath: string, hosts: string[]) {
  const store = new ChannelStore({ dbPath });
  try {
    store.initializeParentEnumeration(hosts);
    for (const host of hosts) store.markInstanceHealthOk(host);
  } finally {
    store.close();
  }
}

/** Confirm listing completion without marking channels healthy.
 * Channel-health scenarios intentionally start with unresolved observations.
 */
function prepareHealth(dbPath: string, hosts: string[]) {
  const store = new ChannelStore({ dbPath });
  try {
    store.initializeParentEnumeration(hosts);
    for (const host of hosts) {
      store.markInstanceHealthOk(host);
      store.updateChannelProgress(host, 'done', 0);
    }
  } finally {
    store.close();
  }
}
for (const [name, limit, total, count, status] of [
  ["terminal page drops an eligible channel", 1, 2, 2, "in_progress"],
  ["exact terminal budget", 2, 2, 2, "done"],
  ["budget ends before remote end", 2, 100, 50, "in_progress"],
  ["unlimited terminal page", 0, 2, 2, "done"]
] as const) {
  test(name, async () => {
    const f = fixture(), old = globalThis.fetch;
    prepareListing(f.dbPath, ['a.example']);
    globalThis.fetch = async () => new Response(JSON.stringify({ total, data: Array.from({ length: count }, (_, i) => ({ id: i + 1, name: `c${i}`, host: "a.example" })) }));
    try {
      await crawlChannels({ ...f.options, hosts: ["a.example"], maxChannels: limit, alreadyInitialized: true });
      const db = new Database(f.dbPath), progress = db.prepare("SELECT status,last_start FROM channel_crawl_progress WHERE instance_domain='a.example'").get() as any;
      assert.equal(progress.status, status);
      if (status !== "done")
        assert.equal(progress.last_start, 0);
      assert.equal((db.prepare("SELECT COUNT(*) n FROM channels WHERE instance_domain='a.example' AND channel_id!='old'").get() as any).n, limit || count);
      db.close();
    }
    finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
for (const payload of [{ total: 2, data: {} }, { total: -1, data: [] }, { total: 1.5, data: [] }, { total: "2", data: [] }, { total: 0, data: [{ id: 1, host: "a.example" }] }]) {
  test(`invalid channel page cannot become done: ${JSON.stringify(payload)}`, async () => {
    const f = fixture(), old = globalThis.fetch;
    prepareListing(f.dbPath, ['a.example']);
    globalThis.fetch = async () => new Response(JSON.stringify(payload));
    try {
      await crawlChannels({ ...f.options, hosts: ["a.example"], alreadyInitialized: true });
      const db = new Database(f.dbPath);
      assert.equal((db.prepare("SELECT status FROM channel_crawl_progress WHERE instance_domain='a.example'").get() as any).status, "error");
      assert.equal((db.prepare("SELECT COUNT(*) n FROM channels").get() as any).n, 2);
      db.close();
    }
    finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
for (const mode of ["only-a", "empty-array", "empty-file", "intersection", "exclude-a"]) {
  test(`channel health uses exact host intersection: ${mode}`, async () => {
    const f = fixture(), old = globalThis.fetch, requests: string[] = [];
    prepareHealth(f.dbPath, ['a.example', 'b.example']);
    const file = path.join(path.dirname(f.dbPath), "include.txt");
    fs.writeFileSync(file, mode === "intersection" ? "b.example\n" : "");
    const exclude = path.join(path.dirname(f.dbPath), "exclude.txt");
    fs.writeFileSync(exclude, "a.example\n");
    globalThis.fetch = async (input) => { requests.push(new URL(String(input)).hostname); return new Response('{"total":0,"data":[]}'); };
    try {
      await checkChannelHealth({ ...f.options, hosts: mode === "empty-array" ? [] : ["a.example"], hostsFile: ["empty-file", "intersection"].includes(mode) ? file : null, excludeHostsFile: mode === "exclude-a" ? exclude : null });
      assert.deepEqual(requests, mode === "only-a" ? ["a.example"] : []);
      const db = new Database(f.dbPath);
      assert.equal((db.prepare("SELECT health_status FROM channels WHERE instance_domain='b.example'").get() as any).health_status, null);
      db.close();
    }
    finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
test("empty enumeration scope preserves progress and makes no requests", async () => {
  const f = fixture(), old = globalThis.fetch, db = new Database(f.dbPath);
  db.exec("INSERT INTO channel_crawl_progress VALUES('b.example','done',0,1)");
  db.close();
  let requests = 0;
  globalThis.fetch = async () => { requests++; return new Response('{"total":0,"data":[]}'); };
  try {
    await crawlChannels({ ...f.options, hosts: [] });
    assert.equal(requests, 0);
    const read = new Database(f.dbPath);
    assert.deepEqual(read.prepare('SELECT * FROM channel_crawl_progress').all(), [{ instance_domain: 'b.example', status: 'done', last_start: 0, updated_at: 1 }]);
    read.close();
  }
  finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});
test("new-only budget refreshes existing count without consuming the insertion budget", async () => {
  const f = fixture(), old = globalThis.fetch;
  prepareListing(f.dbPath, ['a.example']);
  globalThis.fetch = async () => new Response(JSON.stringify({ total: 3, data: [{ id: 'old', name: 'old', host: 'a.example', displayName: 'replace forbidden', videosCount: 7 }, { id: 'new1', name: 'new1', host: 'a.example' }, { id: 'new2', name: 'new2', host: 'a.example' }] }));
  try {
    await crawlChannels({ ...f.options, hosts: ['a.example'], maxChannels: 1, newOnly: true, alreadyInitialized: true });
    const db = new Database(f.dbPath);
    assert.deepEqual(db.prepare("SELECT display_name,videos_count FROM channels WHERE channel_id='old' AND instance_domain='a.example'").get(), { display_name: 'canonical', videos_count: 7 });
    assert.equal((db.prepare("SELECT COUNT(*) n FROM channels WHERE instance_domain='a.example'").get() as any).n, 2);
    assert.equal((db.prepare("SELECT status FROM channel_crawl_progress WHERE instance_domain='a.example'").get() as any).status, 'in_progress');
    db.close();
  }
  finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});
for (const body of [{ hello: 'not a PeerTube page' }, { total: -1, data: [] }, { total: 0, data: [{}] }]) {
  test(`malformed health JSON cannot mark a channel healthy: ${JSON.stringify(body)}`, async () => {
    const f = fixture(), old = globalThis.fetch;
    prepareHealth(f.dbPath, ['a.example']);
    globalThis.fetch = async () => new Response(JSON.stringify(body));
    try {
      await checkChannelHealth({ ...f.options, hosts: ['a.example'] });
      const db = new Database(f.dbPath);
      assert.equal((db.prepare("SELECT health_status FROM channels WHERE instance_domain='a.example'").get() as any).health_status, 'error');
      assert.equal((db.prepare("SELECT health_status FROM instances WHERE host='a.example'").get() as any).health_status, 'ok');
      db.close();
    }
    finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
test("proven local outage rejects after in-flight channel checks settle", async () => {
  const f = fixture(), old = globalThis.fetch;
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.upsertChannels([{ channelId: 'second', channelName: 'second', channelUrl: null, displayName: null, instanceDomain: 'a.example', videosCount: null, followersCount: 0, avatarUrl: null }]);
  store.close();
  prepareHealth(f.dbPath, ['a.example']);
  let settled = false;
  globalThis.fetch = async (input) => {
    if (String(input).includes('/old/')) {
      const response = new Response('{}');
      response.json = async () => { throw new NoNetworkError('local network unavailable'); };
      return response;
    }
    await new Promise(resolve => setTimeout(resolve, 10));
    settled = true;
    return new Response('{"total":0,"data":[]}');
  };
  try {
    await assert.rejects(checkChannelHealth({ ...f.options, hosts: ['a.example'], hostConcurrency: 2 }), /local network unavailable/);
    assert.equal(settled, true);
    const db = new Database(f.dbPath);
    assert.equal((db.prepare("SELECT health_status FROM channels WHERE channel_id='old' AND instance_domain='a.example'").get() as any).health_status, null);
    db.close();
  }
  finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});
/** Ordinary video options share the same host boundary across every maintenance mode. */
function videoOptions(options: ChannelCrawlOptions): VideoCrawlOptions {
  return { ...options, existingDbPath: null, stopAfterFullPages: 0, sort: '-publishedAt', maxVideosPages: 1, tagsOnly: false, updateTags: false, commentsOnly: false, refreshThumbnails: false };
}
for (const mode of ['listing', 'metadata', 'thumbnails', 'tags', 'comments', 'update-tags']) {
  test(`video mode cannot broaden explicit empty include: ${mode}`, async () => {
    const f = fixture(), old = globalThis.fetch, db = new Database(f.dbPath);
    db.exec("UPDATE channels SET videos_count=1;INSERT INTO videos(video_id,video_uuid,instance_domain,channel_id,title,last_checked_at,tags_json) VALUES('v','11111111-1111-4111-8111-111111111111','a.example','old','kept',1,'[]');INSERT INTO video_crawl_progress(instance_domain,channel_id,channel_name,status,last_start,updated_at) VALUES('b.example','old','old','done',0,1)");
    db.close();
    const file = path.join(f.dir, 'empty.txt');
    fs.writeFileSync(file, '');
    let requests = 0;
    globalThis.fetch = async () => { requests++; return new Response('{"total":0,"data":[]}'); };
    try {
      await crawlVideos({ ...videoOptions(f.options), hostsFile: file, metadataOnly: mode === 'metadata', refreshThumbnails: mode === 'thumbnails', tagsOnly: mode === 'tags', commentsOnly: mode === 'comments', updateTags: mode === 'update-tags' });
      assert.equal(requests, 0);
      const check = new Database(f.dbPath);
      assert.deepEqual(check.prepare('SELECT title,last_checked_at FROM videos').get(), { title: 'kept', last_checked_at: 1 });
      assert.equal((check.prepare("SELECT status FROM video_crawl_progress WHERE instance_domain='b.example'").get() as any).status, 'done');
      check.close();
    }
    finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
for (const limit of [0, 1]) {
  test(`real host pipeline advances only a fully saved listing: limit=${limit}`, async () => {
    const f = fixture(), old = globalThis.fetch, requests: string[] = [];
    globalThis.fetch = async (input) => {
      const url = String(input);
      requests.push(url);
      return new Response(JSON.stringify(url.includes('count=1') ? { total: 0, data: [] } : url.includes('/video-channels?') ? { total: 2, data: [{ id: 1, name: 'one', host: 'a.example' }, { id: 2, name: 'two', host: 'a.example' }] } : { total: 0, data: [] }));
    };
    try {
      await crawlHostPipeline({ channels: { ...f.options, hosts: ['a.example'], maxChannels: limit }, counts: f.options, videos: videoOptions(f.options) });
      assert.equal(requests.some(url => url.includes('/videos?')), limit === 0);
      const check = new Database(f.dbPath);
      assert.equal((check.prepare("SELECT status FROM channel_crawl_progress WHERE instance_domain='a.example'").get() as any).status, limit === 0 ? 'done' : 'in_progress');
      check.close();
    }
    finally {
      globalThis.fetch = old;
      f.cleanup();
    }
  });
}
for (const host of [null, 'a.example']) {
  test(`instance health CLI cannot override an empty file with --host: ${host}`, () => {
    const f = fixture(), file = path.join(f.dir, 'empty.txt');
    fs.writeFileSync(file, '');
    try {
      const args = [new URL('../../src/instances-health-cli.js', import.meta.url).pathname, '--db', f.dbPath, '--hosts-file', file];
      if (host)
        args.push('--host', host);
      const result = spawnSync(process.execPath, args, { encoding: 'utf8', timeout: 5000 });
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /instances=0/);
      const db = new Database(f.dbPath);
      assert.equal((db.prepare("SELECT COUNT(*) n FROM instances WHERE health_status='ok'").get() as any).n, 2);
      db.close();
    }
    finally {
      f.cleanup();
    }
  });
}
test("resuming an incomplete legacy page cannot skip locally discarded channels", async () => {
  const f = fixture(), old = globalThis.fetch, db = new Database(f.dbPath);
  db.exec("INSERT INTO channel_crawl_progress VALUES('a.example','in_progress',50,1)");
  db.close();
  const starts: string[] = [];
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    if (url.searchParams.get('count') === '50') starts.push(url.searchParams.get('start')!);
    return new Response('{"total":0,"data":[]}');
  };
  try {
    await crawlChannels({ ...f.options, hosts: ['a.example'], resume: true });
    assert.deepEqual(starts, ['0']);
  }
  finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});
test("historical errored host cannot be classified directly into child stages", () => {
  const f = fixture(), db = new Database(f.dbPath);
  db.exec("INSERT INTO channel_crawl_progress VALUES('a.example','error',0,1);INSERT INTO channel_crawl_progress VALUES('b.example','done',0,1)");
  db.close();
  try {
    const state = new ChannelStore({ dbPath: f.dbPath });
    state.initializeParentEnumeration(['a.example', 'b.example']);
    assert.deepEqual(state.listFreshHealthyHosts(['a.example', 'b.example']), []);
    state.close();
  }
  finally {
    f.cleanup();
  }
});

test("local outage stops queued hosts while another request drains", async () => {
  const f = fixture(), old = globalThis.fetch;
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.markInstanceHealthOk('c.example');
  for (const id of ['old', 'slow']) {
    store.upsertChannels([{ channelId: id, channelName: id, channelUrl: null, displayName: null, instanceDomain: 'c.example', videosCount: null, followersCount: 0, avatarUrl: null }]);
  }
  store.close();
  prepareHealth(f.dbPath, ['a.example', 'b.example', 'c.example']);
  const requested: string[] = [];
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    requested.push(url.hostname);
    if (url.hostname === 'c.example' && url.pathname.includes('/old/')) {
      const response = new Response('{}');
      response.json = async () => { throw new NoNetworkError('local outage'); };
      return response;
    }
    await new Promise(resolve => setTimeout(resolve, url.hostname === 'c.example' ? 50 : 10));
    return new Response('{"total":0,"data":[]}');
  };
  try {
    await assert.rejects(checkChannelHealth({ ...f.options, concurrency: 2, hostConcurrency: 2 }), /local outage/);
    assert.ok(requested.includes('b.example'));
    assert.ok(!requested.includes('a.example'));
  } finally {
    globalThis.fetch = old;
    f.cleanup();
  }
});

test("healthy complete parent admits child video work and later error blocks retained progress", () => {
  const f = fixture();
  try {
    const parent = new ChannelStore({ dbPath: f.dbPath });
    parent.initializeParentEnumeration(["a.example"]);
    parent.markInstanceHealthOk("a.example");
    parent.updateChannelHealthOk("old", "a.example");
    parent.updateChannelVideosCount("old", "a.example", 4);
    parent.updateChannelProgress("a.example", "done", 0);
    const videos = new VideoStore({ dbPath: f.dbPath });
    const ready = videos.listChannelsWithVideos(1, ["a.example"]);
    assert.equal(ready.length, 1);
    videos.prepareVideoProgress(ready, true, ["a.example"]);
    assert.equal(videos.listVideoWorkItems(["pending"], ["a.example"]).length, 1);
    parent.updateChannelHealthError("old", "a.example", "unavailable");
    assert.deepEqual(videos.listVideoWorkItems(["pending"], ["a.example"]), []);
    videos.close();
    parent.close();
  } finally {
    f.cleanup();
  }
});

test("legacy completed progress without host provenance cannot select child work", () => {
  const f = fixture();
  try {
    const db = new Database(f.dbPath);
    db.exec("INSERT INTO channel_crawl_progress VALUES('a.example','done',0,1)");
    db.close();
    const parent = new ChannelStore({ dbPath: f.dbPath });
    assert.throws(() => parent.assertParentEnumerationPrepared(["a.example"]));
    parent.close();
  } finally {
    f.cleanup();
  }
});


test("explicit process-wide outage aborts instance probe without remote health write", async () => {
  const f = fixture(), old = globalThis.fetch;
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.initializeParentEnumeration(["a.example"]);
  store.close();
  let requests = 0;
  globalThis.fetch = async () => { requests++; throw new NoNetworkError("confirmed local outage"); };
  try {
    const opt = { dbPath: f.dbPath, concurrency: 1, hostDelayMs: 0,
      timeoutMs: 100, maxRetries: 0, minAgeDays: null, minAgeMin: null,
      minAgeSec: null, hostsFile: null, host: null, errorsOnly: false,
      hosts: ["a.example"] };
    await assert.rejects(checkInstancesHealth(opt), error => isNoNetworkError(error));
    assert.equal(requests, 1);
    const db = new Database(f.dbPath);
    assert.deepEqual(db.prepare("SELECT health_status,health_error FROM instances WHERE host='a.example'").get(),
      { health_status: null, health_error: null });
    db.close();
  } finally { globalThis.fetch = old; f.cleanup(); }
});

test("ordinary per-target socket reset persists remote health error, not a local outage", async () => {
  const f = fixture(), old = globalThis.fetch;
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.initializeParentEnumeration(["a.example"]);
  store.close();
  globalThis.fetch = async () => { throw Object.assign(new Error("peer disconnected"), { code: "ECONNRESET" }); };
  try {
    await checkInstancesHealth({ dbPath: f.dbPath, concurrency: 1, hostDelayMs: 0,
      timeoutMs: 100, maxRetries: 0, minAgeDays: null, minAgeMin: null,
      minAgeSec: null, hostsFile: null, host: null, errorsOnly: false,
      hosts: ["a.example"] });
    const db = new Database(f.dbPath);
    assert.equal((db.prepare("SELECT health_status FROM instances WHERE host='a.example'").get() as any).health_status, "error");
    db.close();
  } finally { globalThis.fetch = old; f.cleanup(); }
});

test("count repair ignores unrelated legacy host but rejects actual unproven candidate", async () => {
  const f = fixture(), old = globalThis.fetch;
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.initializeParentEnumeration(["a.example"]);
  store.markInstanceHealthOk("a.example");
  store.updateChannelProgress("a.example", "done", 0);
  store.updateChannelHealthOk("old", "a.example");
  store.updateChannelVideosCountError("old", "a.example", "previous failure");
  store.close();
  const db = new Database(f.dbPath);
  db.exec("INSERT INTO channel_crawl_progress VALUES('b.example','done',0,1)");
  db.close();
  const requested: string[] = [];
  globalThis.fetch = async input => {
    requested.push(String(input));
    return new Response(JSON.stringify({ total: 0, data: [] }));
  };
  const options = { dbPath: f.dbPath, hostsFile: null, excludeHostsFile: null,
    concurrency: 1, hostConcurrency: 1, hostDelayMs: 0, timeoutMs: 100,
    maxRetries: 0, resume: true, errorsOnly: true };
  try {
    await crawlChannelVideosCount(options);
    assert.equal(requested.length, 1);
    assert.ok(requested[0].includes("a.example"));
    const check = new Database(f.dbPath);
    assert.equal((check.prepare("SELECT videos_count FROM channels WHERE instance_domain='a.example'").get() as any).videos_count, 0);
    check.exec("UPDATE channels SET last_error_source='videos_count' WHERE instance_domain='b.example'");
    check.close();
    await assert.rejects(crawlChannelVideosCount(options), /Parent enumeration not initialized for b.example/);
    assert.equal(requested.length, 1);
  } finally { globalThis.fetch = old; f.cleanup(); }
});
