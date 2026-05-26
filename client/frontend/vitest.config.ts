/**
 * Vitest configuration for focused frontend DOM/unit characterization tests.
 */

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.ts"]
  }
});
