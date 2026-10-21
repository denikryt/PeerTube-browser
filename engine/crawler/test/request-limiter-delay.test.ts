/** A stalled event loop must not turn overdue request timers into a burst. */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequestLimiter } from "../src/request-limiter.js";

test("host delay separates actual starts after an event-loop stall", async () => {
  const limiter = createRequestLimiter(3, 25);
  const starts: number[] = [];
  await Promise.all(Array.from({ length: 3 }, (_, index) => limiter.run(async () => {
    starts.push(performance.now());
    if (index === 0) {
      // Other holders reserve their starts before this callback blocks the loop.
      // Both timers then become overdue, reproducing the catch-up burst.
      await new Promise<void>((resolve) => setImmediate(resolve));
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
    }
  })));
  assert.equal(starts.length, 3);
  for (let i = 1; i < starts.length; i++) {
    assert.ok(starts[i] - starts[i - 1] >= 24,
      `actual gap ${starts[i] - starts[i - 1]}ms must preserve host delay`);
  }
});
