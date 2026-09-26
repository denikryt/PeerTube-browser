/**
 * Shared setup for jsdom frontend characterization tests.
 */

import { afterEach, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.body.innerHTML = "";
});
