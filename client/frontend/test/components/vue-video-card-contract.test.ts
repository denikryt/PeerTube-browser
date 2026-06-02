/**
 * Regression tests for the Vue feed/search video-card contract.
 *
 * Home and Search must share one YouTube-style card component: thumbnail first,
 * compact metadata row below, no material-card body, and no reaction controls in
 * feed/search contexts. The detail page keeps a separate compact similar-card.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const videoCard = readFileSync(join(process.cwd(), "src", "components", "VideoCard.vue"), "utf8");
const homeView = readFileSync(join(process.cwd(), "src", "views", "HomeView.vue"), "utf8");
const searchView = readFileSync(join(process.cwd(), "src", "views", "SearchView.vue"), "utf8");
const videosCss = readFileSync(join(process.cwd(), "src", "videos.css"), "utf8");

describe("Vue feed/search video card contract", () => {
  it("uses one shared component from both Home and Search", () => {
    expect(homeView).toContain('import VideoCard from "../components/VideoCard.vue"');
    expect(searchView).toContain('import VideoCard from "../components/VideoCard.vue"');
    expect(homeView).toContain("<VideoCard");
    expect(searchView).toContain("<VideoCard");
  });

  it("renders a YouTube-style thumbnail plus metadata row instead of a material body card", () => {
    expect(videoCard).toContain('class="video-card-thumbnail-link"');
    expect(videoCard).toContain('class="video-card-meta"');
    expect(videoCard).toContain('class="video-card-text"');
    expect(videoCard).toContain('class="video-card-menu"');
    expect(videoCard).not.toContain('class="video-body"');
    expect(videoCard).not.toContain('class="video-stats"');
    expect(videoCard).not.toContain("iconThumbUp");
    expect(videoCard).not.toContain("iconThumbDown");
  });

  it("pins the CSS to a borderless feed-card surface with compact text", () => {
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*background:\s*transparent;/);
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*box-shadow:\s*none;/);
    expect(videosCss).toMatch(/\.video-card-meta\s*\{/);
    expect(videosCss).toMatch(/\.video-card-menu\s*\{/);
    expect(videosCss).toMatch(/\.video-card \.video-title\s*\{[\s\S]*font-size:\s*1rem;/);
  });
});
