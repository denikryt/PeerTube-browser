/** Regression tests for shared Home/Search video-filter URL state. */
import { describe, expect, it } from "vitest";
import {
  emptyVideoFilters,
  homeSelectionKey,
  parseHomeMode,
  parseVideoFilterQuery,
  serializeVideoFilters,
  searchSelectionKey
} from "../../src/state/video-filters";

describe("video filter route state", () => {
  it("round-trips the four supported filters and canonical Home modes", () => {
    const filters = parseVideoFilterQuery({
      language: " uk ",
      category: " Education ",
      tag: " linux ",
      instance: " example.org "
    });

    expect(filters).toEqual({ language: "uk", category: "Education", tag: "linux", instance: "example.org" });
    expect(serializeVideoFilters(filters)).toEqual({ language: "uk", category: "Education", tag: "linux", instance: "example.org" });
    expect(parseHomeMode("fresh")).toBe("fresh");
    expect(parseHomeMode(undefined)).toBe("recommendations");
    expect(homeSelectionKey("fresh", filters)).toBe('["fresh","uk","Education","linux","example.org"]');
    expect(searchSelectionKey("  kernel ", filters)).toBe('["kernel","uk","Education","linux","example.org"]');
  });

  it("drops blank control values and rejects unsupported Home modes to the default", () => {
    expect(parseVideoFilterQuery({ language: " ", category: null, tag: "", instance: undefined })).toEqual(emptyVideoFilters());
    expect(serializeVideoFilters({ language: " ", category: null, tag: "", instance: "  " })).toEqual({});
    expect(parseHomeMode("personalized")).toBe("recommendations");
    expect(homeSelectionKey("recommendations", emptyVideoFilters())).toBe('["recommendations",null,null,null,null]');
  });
});
