/**
 * Regression tests for the Vue feed/search video-card contract.
 *
 * Home and Search must share one YouTube-style card component: thumbnail first,
 * compact metadata row below, no material-card body, and compact view/time
 * metadata in feed/search contexts. The detail page keeps a separate compact similar-card.
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
    expect(videoCard).toContain('class="video-meta-views"');
    expect(videoCard).toContain("iconPlayOutline");
    expect(videoCard).not.toContain("▶");
    expect(videoCard).not.toContain("iconThumbDown");
    expect(videoCard).not.toContain('data-stat="dislikes"');
    expect(videoCard).not.toContain('class="video-body"');
    expect(videoCard).not.toContain('class="video-stats"');
  });

  it("keeps feed metadata compact and clamps titles to two lines", () => {
    expect(videoCard).toContain('class="video-meta-views"');
    expect(videoCard).toContain("iconPlayOutline");
    expect(videoCard).not.toContain('views`');
    expect(videosCss).toMatch(/\.video-card \.video-title\s*\{[\s\S]*-webkit-line-clamp:\s*2;/);
    expect(videosCss).toMatch(/\.video-card \.video-title\s*\{[\s\S]*overflow:\s*hidden;/);
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

  it("keeps the instance label beside its channel while metadata stays focused on views, likes, and age", () => {
    expect(videoCard).toContain("instanceDomain");
    expect(videoCard).toContain('class="channel-instance"');
    expect(videoCard).toContain('class="channel-instance-host"');
    expect(videoCard).toContain('class="video-meta-views"');
    expect(videoCard).toContain('class="video-card-likes"');
    expect(videoCard).toContain("iconThumbUp");
    expect(videoCard).not.toContain("👍");
    expect(videoCard).not.toContain('class="video-card-taxonomy"');
    expect(videoCard.indexOf('class="video-meta-views"')).toBeLessThan(
      videoCard.indexOf('class="video-card-likes"')
    );
    expect(videoCard.indexOf('class="video-card-likes"')).toBeLessThan(
      videoCard.indexOf('class="video-meta-time"')
    );
    expect(videoCard).not.toContain('aria-label="Likes"> ·');
  });

  it("pins the CSS to a borderless feed-card surface with compact text", () => {
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*background:\s*transparent;/);
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*box-shadow:\s*none;/);
    expect(videosCss).toMatch(/\.video-card\s*\{[\s\S]*padding:\s*0\.5rem;/);
    expect(videosCss).toMatch(/\.video-card:hover,\n\.video-card:focus-within\s*\{[\s\S]*transform:\s*none;/);
    expect(videosCss).toMatch(/\.video-card:hover,\n\.video-card:focus-within\s*\{[\s\S]*background:\s*rgba\(31, 27, 22, 0\.14\);/);
    expect(videosCss).toMatch(/\.video-card-meta\s*\{/);
    expect(videosCss).toMatch(/\.video-card-menu\s*\{/);
    expect(videosCss).toMatch(/\.video-card \.video-title\s*\{[\s\S]*font-size:\s*1rem;/);
    expect(videosCss).toMatch(/\.video-meta-views\s*\{[\s\S]*vertical-align:\s*middle;/);
    expect(videosCss).toMatch(/\.video-meta-views > span\s*\{[\s\S]*display:\s*inline-flex;/);
    expect(videosCss).toMatch(/\.video-meta-views svg\s*\{[\s\S]*display:\s*block;/);
    expect(videosCss).toMatch(/\.video-card \.video-meta\s*\{[\s\S]*display:\s*flex;[\s\S]*align-items:\s*center;/);
    expect(videosCss).toMatch(/\.video-card-likes > span\s*\{[\s\S]*display:\s*inline-flex;/);
    expect(videosCss).toMatch(/\.video-card-likes svg\s*\{[\s\S]*display:\s*block;/);
    expect(videosCss).toMatch(/\.video-card \.channel-link\s*\{[\s\S]*flex:\s*0 0 auto;/);
    expect(videosCss).toMatch(/\.channel-instance-host\s*\{[\s\S]*text-overflow:\s*ellipsis;/);
    expect(videosCss).toMatch(/\.video-card \.channel-instance::before\s*\{[\s\S]*margin:\s*0 0\.3rem;/);
  });
});
