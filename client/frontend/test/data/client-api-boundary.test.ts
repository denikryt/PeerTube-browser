/**
 * Static frontend boundary checks for project API calls.
 */

import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = join(process.cwd(), "src");
const forbidden = [
  "/internal/events/ingest",
  "/internal/videos/resolve",
  "/internal/videos/metadata",
  "ENGINE_API_BASE",
  "7072"
];

function files(dir: string): string[] {
  return readdirSync(dir)
    .flatMap((entry) => {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) return files(path);
      return path.endsWith(".ts") ? [path] : [];
    });
}

describe("frontend API boundary", () => {
  it("does not call Engine internal/read APIs directly from production source", () => {
    const matches = files(root).flatMap((path) => {
      const text = readFileSync(path, "utf8");
      return forbidden
        .filter((needle) => text.includes(needle))
        .map((needle) => `${relative(root, path)}:${needle}`);
    });

    expect(matches).toEqual([]);
  });
});
