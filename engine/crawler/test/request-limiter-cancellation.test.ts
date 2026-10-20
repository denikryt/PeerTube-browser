/** A request reserved before a cross-host fatal signal must not start afterwards. */
import assert from "node:assert/strict";
import test from "node:test";
import { createRequestLimiter } from "../src/request-limiter.js";

/** FIFO waiters recheck the invocation state AFTER acquiring the shared slot. */
test("queued per-host request refuses a new HTTP start after sibling outage", async () => {
  let stopped = false;
  let releaseFirst: (() => void) | undefined;
  const firstMayFinish = new Promise<void>(resolve => { releaseFirst = resolve; });
  const started: string[] = [];
  let signalStarted: (() => void) | undefined;
  const firstStarted = new Promise<void>(resolve => { signalStarted = resolve; });
  const limiter = createRequestLimiter(1, 0, () => {
    if (stopped) throw new Error("confirmed local outage");
  });
  const first = limiter.run(async () => { started.push("first"); signalStarted?.(); await firstMayFinish; });
  await firstStarted;
  const queued = limiter.run(async () => { started.push("queued"); });
  stopped = true;
  releaseFirst?.();
  await first;
  await assert.rejects(queued, /confirmed local outage/);
  assert.deepEqual(started, ["first"]);
});

test("healthy queued per-host work retains FIFO ordering and remains permitted", async () => {
  const started: number[] = [];
  const limiter = createRequestLimiter(1, 0, () => {});
  const [a, b] = await Promise.all([
    limiter.run(async () => { started.push(1); return 1; }),
    limiter.run(async () => { started.push(2); return 2; }),
  ]);
  assert.deepEqual([a, b], [1, 2]);
  assert.deepEqual(started, [1, 2]);
});


test("host start-delay cannot release a newly stopped request", async () => {
  let stopped = false;
  const started: string[] = [];
  const limiter = createRequestLimiter(2, 50, () => {
    if (stopped) throw new Error("confirmed local outage");
  });
  const first = limiter.run(async () => {
    started.push("first");
    // A sibling outage can be signalled while another request is waiting for
    // its reserved host start time, even when the first operation succeeds.
    stopped = true;
  });
  const delayed = limiter.run(async () => { started.push("delayed"); });
  await first;
  await assert.rejects(delayed, /confirmed local outage/);
  assert.deepEqual(started, ["first"]);
});
