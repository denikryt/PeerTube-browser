/** Regression contract for the persistent landing navigation and search entry. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const headerSource = readFileSync(join(process.cwd(), "src", "components", "AppHeader.vue"), "utf8");
const homeSource = readFileSync(join(process.cwd(), "src", "views", "HomeView.vue"), "utf8");
const styles = readFileSync(join(process.cwd(), "src", "videos.css"), "utf8");

describe("landing shell", () => {
  it("keeps combined search and discovery destinations in the landing shell", () => {
    expect(headerSource).toContain('name: "search"');
    expect(headerSource).toContain("Search videos, channels, topics…");
    expect(headerSource).toContain(">Fresh<");
    expect(headerSource).toContain(">Trending<");
    expect(headerSource).toContain("Categories");
    expect(headerSource).toContain("Tags");
    expect(headerSource).toContain("name: 'categories'");
    expect(headerSource).toContain("name: 'tags'");
    expect(headerSource).toContain("name: 'channels'");
  });

  it("keeps shared controls collapsible without replacing VideoCard", () => {
    expect(homeSource).toContain("home-filters");
    expect(homeSource).toContain("<details");
    expect(homeSource).toContain("<VideoFilterControls");
    expect(homeSource).toContain("<VideoCard");
    expect(styles).toContain(".home-toolbar");
    expect(styles).toContain(".home-filters");
    expect(styles).toContain(".app-sidebar");
  });
});
