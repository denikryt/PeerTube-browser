/**
 * Regression tests for globally imported Vue page styles.
 *
 * The Vue SPA imports the old page styles once at application startup. Route
 * detail CSS must therefore scope selectors that share component class names,
 * otherwise feed/search cards inherit video-detail sizing and spacing.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const videoCss = readFileSync(join(process.cwd(), "src", "video.css"), "utf8");
const videosCss = readFileSync(join(process.cwd(), "src", "videos.css"), "utf8");

describe("global CSS route scoping", () => {
  it("keeps video-detail selectors from overriding reusable video cards", () => {
    expect(videoCss).not.toMatch(/^\.video-title\s*\{/m);
    expect(videoCss).not.toMatch(/^\.channel-avatar\s*\{/m);
    expect(videoCss).not.toMatch(/^\.channel-meta\s*\{/m);
    expect(videoCss).toMatch(/\.video-main \.video-title\s*\{/);
    expect(videoCss).toMatch(/\.video-main \.channel-avatar\s*\{/);
  });

  it("pins the compact feed-card contract with component-specific selectors", () => {
    expect(videosCss).toMatch(/\.video-card \.video-title\s*\{/);
    expect(videosCss).toMatch(/font-size:\s*1\.02rem/);
    expect(videosCss).toMatch(/\.video-card \.channel-avatar\s*\{/);
    expect(videosCss).toMatch(/width:\s*34px/);
  });
});
