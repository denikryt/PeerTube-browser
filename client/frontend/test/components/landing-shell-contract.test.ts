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

  it("does not render a discovery page title or visible-card count above any shared feed", () => {
    expect(homeSource).not.toContain("pageTitle");
    expect(homeSource).not.toContain("Showing ${visibleItems.value.length} videos");
    expect(homeSource).toContain('class="home-filters"');
  });

  it("scrolls discovery content independently while the desktop navigation and search shell stay fixed", () => {
    expect(styles).toMatch(/\.videos-app\s*\{[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/);
    expect(styles).toMatch(/\.videos-app > \.videos-main\s*\{[\s\S]*min-height:\s*0;[\s\S]*overflow-y:\s*auto;/);
    expect(styles).toMatch(/@media \(max-width: 900px\)\s*\{[\s\S]*\.videos-app\s*\{[\s\S]*height:\s*auto;[\s\S]*overflow:\s*visible;/);
  });

  it("centers the global search field within the card-content column", () => {
    expect(styles).toMatch(/\.landing-header \.landing-search\s*\{[\s\S]*margin-inline:\s*auto;/);
    expect(styles).toMatch(/\.landing-header \.landing-search\s*\{[\s\S]*width:\s*min\(760px, 100%\);/);
    expect(styles).not.toContain("translateX(calc(var(--landing-sidebar-width) / -2))");
  });
});
