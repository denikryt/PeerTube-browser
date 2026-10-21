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
});
