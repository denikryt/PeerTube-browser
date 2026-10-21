/** Resume and host-outage scenarios through real crawler workers and SQLite. */
import assert from "node:assert/strict";
import test from "node:test";
import Database from "better-sqlite3";
import { ChannelStore } from "../../src/db/channels.js";
import { crawlChannels, checkChannelHealth, type ChannelCrawlOptions } from "../../src/channels-worker.js";
import { checkInstancesHealth } from "../../src/instances-health-cli.js";
import { NoNetworkError } from "../../src/http.js";
import { createTempDb } from "./helpers.js";

/** Build a selected, initialized host set with one durable completed probe. */
function fixture() {
  const temp = createTempDb("crawler-resume");
  const store = new ChannelStore({ dbPath: temp.dbPath });
  for (const host of ["a.example", "b.example"]) store.markInstanceDone(host);
  store.initializeParentEnumeration(["a.example", "b.example"]);
  store.markInstanceHealthOk("a.example");
  store.close();
  const options: ChannelCrawlOptions = {
    dbPath: temp.dbPath, hostsFile: null, excludeHostsFile: null,
    concurrency: 1, hostConcurrency: 1, hostDelayMs: 0, timeoutMs: 100,
    maxRetries: 0, newOnly: true, maxInstances: 0, maxChannels: 0,
    resume: true, errorsOnly: false
  };
  return { ...temp, options };
}

test("resume probes only unobserved hosts, keeps completed listings, and replays only an unfinished host from page zero", async () => {
  const f = fixture();
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.updateChannelProgress("a.example", "done", 0);
  store.updateChannelProgress("b.example", "in_progress", 0);
  store.upsertChannels([{ channelId: "saved", channelName: "saved", channelUrl: null,
    displayName: "saved before interruption", instanceDomain: "b.example",
    videosCount: 1, followersCount: null, avatarUrl: null }]);
  store.close();
  const previous = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    requests.push(`${url.hostname}:${url.searchParams.get("count")}:${url.searchParams.get("start")}`);
    return new Response(JSON.stringify({ total: url.searchParams.get("count") === "1" ? 0 : 1,
      data: url.searchParams.get("count") === "1" ? [] : [{ id: "saved", name: "saved", host: "b.example" }] }));
  };
  try {
    await checkInstancesHealth({ dbPath: f.dbPath, hosts: ["a.example", "b.example"],
      concurrency: 1, hostDelayMs: 0, timeoutMs: 100, maxRetries: 0,
      minAgeDays: null, minAgeMin: null, minAgeSec: null, hostsFile: null,
      host: null, errorsOnly: false, skipObserved: true });
    await crawlChannels({ ...f.options, alreadyInitialized: true });
    assert.deepEqual(requests, ["b.example:1:0", "b.example:50:0"]);
    const db = new Database(f.dbPath, { readonly: true });
    assert.deepEqual(db.prepare("SELECT instance_domain,status FROM channel_crawl_progress ORDER BY instance_domain").all(),
      [{ instance_domain: "a.example", status: "done" }, { instance_domain: "b.example", status: "done" }]);
    assert.equal((db.prepare("SELECT COUNT(*) n FROM channels WHERE channel_id='saved' AND instance_domain='b.example'").get() as { n: number }).n, 1);
    db.close();
  } finally { globalThis.fetch = previous; f.cleanup(); }
});

test("resume checks only channel health rows left unresolved by an interruption", async () => {
  const f = fixture();
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.updateChannelProgress("a.example", "done", 0);
  for (const name of ["saved", "pending"]) {
    store.upsertChannels([{ channelId: name, channelName: name,
      channelUrl: null, displayName: null, instanceDomain: "a.example",
      videosCount: null, followersCount: null, avatarUrl: null }]);
  }
  store.updateChannelHealthOk("saved", "a.example");
  store.close();
  const previous = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async input => {
    requests.push(new URL(String(input)).pathname);
    return new Response('{"total":0,"data":[]}');
  };
  try {
    await checkChannelHealth({ ...f.options, hosts: ["a.example"] });
    assert.deepEqual(requests, ["/api/v1/video-channels/pending/videos"]);
    const db = new Database(f.dbPath, { readonly: true });
    assert.deepEqual(db.prepare("SELECT channel_id,health_status FROM channels WHERE instance_domain='a.example' ORDER BY channel_id").all(),
      [{ channel_id: "pending", health_status: "ok" }, { channel_id: "saved", health_status: "ok" }]);
    db.close();
  } finally { globalThis.fetch = previous; f.cleanup(); }
});

for (const hostConcurrency of [1, 2]) test(`channel health stops a failed host with host concurrency ${hostConcurrency}`, async () => {
  const f = fixture();
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.markInstanceHealthOk("b.example");
  for (const host of ["a.example", "b.example"]) {
    store.updateChannelProgress(host, "done", 0);
    for (let i = 0; i < (host === "a.example" ? 8 : 1); i++) {
      store.upsertChannels([{ channelId: String(i), channelName: `channel${i}`,
        channelUrl: null, displayName: null, instanceDomain: host,
        videosCount: null, followersCount: null, avatarUrl: null }]);
    }
  }
  store.close();
  const previous = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    requests.push(`${url.hostname}${url.pathname}`);
    if (url.hostname === "a.example") {
      const error = new Error("connection refused") as Error & { code?: string };
      error.code = "ECONNREFUSED";
      const response = new Response("{}");
      response.json = async () => { throw error; };
      return response;
    }
    return new Response('{"total":0,"data":[]}');
  };
  try {
    await checkChannelHealth({ ...f.options, hosts: ["a.example", "b.example"], hostConcurrency });
    const failedHostRequests = requests.filter(x => x.startsWith("a.example") && x.includes("/channel")).length;
    assert.ok(failedHostRequests >= 3 && failedHostRequests <= 3 + hostConcurrency - 1);
    assert.equal(requests.filter(x => x === "a.example/api/v1/video-channels").length, 1);
    assert.equal(requests.filter(x => x.startsWith("b.example")).length, 1);
    const db = new Database(f.dbPath, { readonly: true });
    assert.equal((db.prepare("SELECT health_status FROM instances WHERE host='a.example'").get() as { health_status: string }).health_status, "error");
    assert.equal((db.prepare("SELECT COUNT(*) n FROM channels WHERE instance_domain='a.example' AND health_status IS NULL").get() as { n: number }).n, 8 - failedHostRequests);
    db.close();
  } finally { globalThis.fetch = previous; f.cleanup(); }
});

test("channel health continues after the parent probe confirms a transient channel failure", async () => {
  const f = fixture();
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.updateChannelProgress("a.example", "done", 0);
  for (let i = 0; i < 5; i++) {
    store.upsertChannels([{ channelId: String(i), channelName: `channel${i}`,
      channelUrl: null, displayName: null, instanceDomain: "a.example",
      videosCount: null, followersCount: null, avatarUrl: null }]);
  }
  store.close();
  const previous = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    requests.push(url.pathname);
    if (/channel[0-2]\/videos/.test(url.pathname)) {
      const response = new Response("{}");
      response.json = async () => {
        const error = new Error("connection refused") as Error & { code?: string };
        error.code = "ECONNREFUSED";
        throw error;
      };
      return response;
    }
    return new Response('{"total":0,"data":[]}');
  };
  try {
    await checkChannelHealth({ ...f.options, hosts: ["a.example"] });
    assert.equal(requests.filter(x => x === "/api/v1/video-channels").length, 1);
    assert.equal(requests.filter(x => x.includes("/videos")).length, 5);
    const db = new Database(f.dbPath, { readonly: true });
    assert.equal((db.prepare("SELECT health_status FROM instances WHERE host='a.example'").get() as { health_status: string }).health_status, "ok");
    assert.equal((db.prepare("SELECT COUNT(*) n FROM channels WHERE instance_domain='a.example' AND health_status='ok'").get() as { n: number }).n, 2);
    db.close();
  } finally { globalThis.fetch = previous; f.cleanup(); }
});

test("local outage during the parent re-probe aborts without storing remote parent failure", async () => {
  const f = fixture();
  const store = new ChannelStore({ dbPath: f.dbPath });
  store.updateChannelProgress("a.example", "done", 0);
  for (let i = 0; i < 4; i++) {
    store.upsertChannels([{ channelId: String(i), channelName: `channel${i}`,
      channelUrl: null, displayName: null, instanceDomain: "a.example",
      videosCount: null, followersCount: null, avatarUrl: null }]);
  }
  store.close();
  const previous = globalThis.fetch;
  globalThis.fetch = async input => {
    const url = new URL(String(input));
    const response = new Response("{}");
    response.json = async () => {
      if (url.pathname === "/api/v1/video-channels") throw new NoNetworkError("local outage");
      const error = new Error("connection refused") as Error & { code?: string };
      error.code = "ECONNREFUSED";
      throw error;
    };
    return response;
  };
  try {
    await assert.rejects(checkChannelHealth({ ...f.options, hosts: ["a.example"] }), /local outage/);
    const db = new Database(f.dbPath, { readonly: true });
    assert.equal((db.prepare("SELECT health_status FROM instances WHERE host='a.example'").get() as { health_status: string }).health_status, "ok");
    assert.equal((db.prepare("SELECT health_status FROM channels WHERE channel_id='3' AND instance_domain='a.example'").get() as { health_status: string | null }).health_status, null);
    db.close();
  } finally { globalThis.fetch = previous; f.cleanup(); }
});
