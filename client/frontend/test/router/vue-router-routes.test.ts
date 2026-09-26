/**
 * Regression tests for the Vue SPA route contract.
 */

import { describe, expect, it } from "vitest";
import { router } from "../../src/router";

describe("Vue Router canonical routes", () => {
  it("declares only the new SPA browser routes", () => {
    const paths = router.getRoutes().map((route) => route.path).sort();

    expect(paths).toEqual(["/", "/about", "/channels", "/search", "/video/:host/:id"].sort());
    expect(paths.some((path) => path.includes(".html"))).toBe(false);
  });
  it("restores browser saved position and otherwise starts at the top", async () => {
    const scrollBehavior = router.options.scrollBehavior;
    expect(scrollBehavior).toBeTypeOf("function");
    const saved = { left: 0, top: 420 };
    expect(await scrollBehavior!(router.resolve("/"), router.resolve("/video/example.org/v1"), saved)).toEqual(saved);
    expect(await scrollBehavior!(router.resolve("/"), router.resolve("/search"), null)).toEqual({ top: 0 });
  });

});
