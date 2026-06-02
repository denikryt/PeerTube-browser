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
    expect(videoCss).toMatch(/\.video-page \.video-main \.channel-meta\s*\{/);
    expect(videoCss).toMatch(/flex-direction:\s*column/);
    expect(videoCss).toMatch(/align-items:\s*flex-start/);
  });

  it("pins the shared YouTube-style feed/search card contract", () => {
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*background:\s*transparent;/);
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*box-shadow:\s*none;/);
    expect(videosCss).toMatch(/\.video-card-meta\s*\{/);
    expect(videosCss).toMatch(/\.video-card \.video-title\s*\{[\s\S]*font-size:\s*1rem;/);
    expect(videosCss).toMatch(/\.video-card \.channel-avatar\s*\{[\s\S]*width:\s*38px/);
  });
});
