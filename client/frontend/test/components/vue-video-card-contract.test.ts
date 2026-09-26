/**
 * Regression tests for the Vue feed/search video-card contract.
 *
 * Home and Search must share one YouTube-style card component: thumbnail first,
 * compact metadata row below, no material-card body, and lightweight reaction
 * counts in feed/search contexts. The detail page keeps a separate compact similar-card.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const videoCard = readFileSync(join(process.cwd(), "src", "components", "VideoCard.vue"), "utf8");
const similarVideoCard = readFileSync(
  join(process.cwd(), "src", "components", "SimilarVideoCard.vue"),
  "utf8"
);
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
    expect(videoCard).toContain('class="video-card-stats"');
    expect(videoCard).toContain("iconThumbUp");
    expect(videoCard).toContain("iconThumbDown");
    expect(videoCard).toContain('data-stat="likes"');
    expect(videoCard).toContain('data-stat="dislikes"');
    expect(videoCard).not.toContain('class="video-body"');
    expect(videoCard).not.toContain('class="video-stats"');
  });

  it("does not read preview_path directly inside the shared card", () => {
    expect(videoCard).not.toContain("preview_path");
    expect(videoCard).not.toContain("previewPath");
  });

  it("falls back to a text placeholder when the thumbnail image fails to load", () => {
    expect(videoCard).toContain("@error=\"thumbErrored = true\"");
    expect(videoCard).toContain('v-if="thumb && !thumbErrored"');
    expect(similarVideoCard).toContain("@error=\"thumbErrored = true\"");
    expect(similarVideoCard).toContain('v-if="thumb && !thumbErrored"');
    expect(similarVideoCard).toContain('class="thumb-fallback"');
  });

  it("renders optional instance/language/category metadata without placeholder labels", () => {
    expect(videoCard).toContain("instanceLabel");
    expect(videoCard).toContain("languageLabel");
    expect(videoCard).toContain("categoryLabel");
    expect(videoCard).toContain('class="video-card-taxonomy"');
    expect(videoCard).not.toContain("Unknown language");
    expect(videoCard).not.toContain("Unknown category");
  });

  it("pins the CSS to a borderless feed-card surface with compact text", () => {
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*background:\s*transparent;/);
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*box-shadow:\s*none;/);
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*padding:\s*0\.5rem;/);
    expect(videosCss).toMatch(/\.video-card:hover,\n\.video-card:focus-within\s*\{[\s\S]*transform:\s*none;/);
    expect(videosCss).toMatch(/\.video-card:hover,\n\.video-card:focus-within\s*\{[\s\S]*background:\s*rgba\(31, 27, 22, 0\.14\);/);
    expect(videosCss).toMatch(/\.video-card-meta\s*\{/);
    expect(videosCss).toMatch(/\.video-card-menu\s*\{/);
    expect(videosCss).toMatch(/\.video-card-stats\s*\{/);
    expect(videosCss).toMatch(/\.video-card-stats \.stat\s*\{/);
    expect(videosCss).toMatch(/\.video-card \.video-title\s*\{[\s\S]*font-size:\s*1rem;/);
  });
});
