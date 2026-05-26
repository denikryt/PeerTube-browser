/**
 * Characterization tests for current feed mode query-state behavior.
 */

import { describe, expect, it } from "vitest";
import { resolveFeedMode, setFeedMode } from "../../src/state/feed-mode";

describe("feed mode state", () => {
  it("uses the current mode=random query contract", () => {
    expect(resolveFeedMode(new URLSearchParams("mode=random"))).toBe("random");
    expect(resolveFeedMode(new URLSearchParams("random=1"))).toBe("recommendations");
    expect(resolveFeedMode(new URLSearchParams("mode=personalized"))).toBe("recommendations");
  });

  it("preserves current URL mutation behavior", () => {
    const location = { href: "https://app.test/videos.html?id=old&uuid=u&api=http://client", search: "?id=old&uuid=u&api=http://client" } as Location;
    setFeedMode("random", location);
    expect(location.search).toBe("api=http%3A%2F%2Fclient&mode=random");

    location.search = "?api=http%3A%2F%2Fclient&mode=random&id=old";
    setFeedMode("recommendations", location);
    expect(location.search).toBe("api=http%3A%2F%2Fclient");
  });
});
