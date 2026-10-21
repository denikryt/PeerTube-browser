/** Regression coverage for metric-first crawler progress messages. */

import assert from "node:assert/strict";
import test from "node:test";

import { createProgressOrdinal, formatMetricLog } from "../../src/log-format.js";

test("formatMetricLog places counters before the event and channel", () => {
  const line = formatMetricLog(
    "videos",
    [["new", 0], ["total", 12]],
    "channel",
    "example.org/music"
  );

  assert.equal(line, "[videos] new=0 total=12 channel example.org/music");
});

test("formatMetricLog preserves metric order for crawler progress", () => {
  const line = formatMetricLog(
    "channels-videos",
    [["updated", 3], ["errors", 2], ["with_videos", 10], ["total", 20]],
    "progress"
  );

  assert.equal(
    line,
    "[channels-videos] updated=3 errors=2 with_videos=10 total=20 progress"
  );
});

test("createProgressOrdinal assigns one global channel position from the crawl total", () => {
  const nextOrdinal = createProgressOrdinal(3);

  assert.equal(nextOrdinal(), "1/3");
  assert.equal(nextOrdinal(), "2/3");
  assert.equal(nextOrdinal(), "3/3");
});
