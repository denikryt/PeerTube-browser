/** Verify the compact relative-time units shown on video cards. */
import { describe, expect, it } from "vitest";
import { formatCompactStatValue, formatTimeAgo } from "../../src/utils/format";

describe("formatTimeAgo", () => {
  it("uses singular labels only for exactly one unit", () => {
    const now = Date.UTC(2026, 0, 1);
    const hour = 60 * 60 * 1000;
    const day = 24 * hour;

    expect(formatTimeAgo(now - hour, now)).toBe("1 hour ago");
    expect(formatTimeAgo(now - day, now)).toBe("1 day ago");
    expect(formatTimeAgo(now - 7 * day, now)).toBe("1 week ago");
    expect(formatTimeAgo(now - 30 * day, now)).toBe("1 month ago");
    expect(formatTimeAgo(now - 365 * day, now)).toBe("1 year ago");
  });

  it("uses hours, days, weeks, months, and years at readable boundaries", () => {
    const now = Date.UTC(2026, 0, 1);
    const hour = 60 * 60 * 1000;
    const day = 24 * hour;

    expect(formatTimeAgo(now - 3 * hour, now)).toBe("3 hours ago");
    expect(formatTimeAgo(now - 2 * day, now)).toBe("2 days ago");
    expect(formatTimeAgo(now - 14 * day, now)).toBe("2 weeks ago");
    expect(formatTimeAgo(now - 60 * day, now)).toBe("2 months ago");
    expect(formatTimeAgo(now - 2 * 365 * day, now)).toBe("2 years ago");
  });
});

describe("formatCompactStatValue", () => {
  it("abbreviates view counts without adding a word label", () => {
    expect(formatCompactStatValue(346_366)).toBe("346.4K");
    expect(formatCompactStatValue(1_250_000)).toBe("1.3M");
  });
});
