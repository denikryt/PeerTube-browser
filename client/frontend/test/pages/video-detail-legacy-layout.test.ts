/**
 * Regression tests for the Vue video-detail layout contract.
 *
 * The route was migrated from a static HTML controller. These checks pin the
 * class names that carry the old visual hierarchy: channel metadata first,
 * metrics/actions in a separate horizontal row, and compact similar cards.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const detailView = readFileSync(join(process.cwd(), "src", "views", "VideoDetailView.vue"), "utf8");
const header = readFileSync(join(process.cwd(), "src", "components", "AppHeader.vue"), "utf8");
const similarCard = readFileSync(join(process.cwd(), "src", "components", "SimilarVideoCard.vue"), "utf8");

describe("video detail legacy visual contract", () => {
  it("uses the old player metadata and action row class structure", () => {
    expect(detailView).toContain('class="channel-row"');
    expect(detailView).toContain('class="channel-line"');
    expect(detailView).toContain('class="meta-chips"');
    expect(detailView).toContain('class="video-meta-row"');
    expect(detailView).toContain('class="video-metrics"');
    expect(detailView).toContain('class="player-actions"');
    expect(detailView).toContain("'ghost-button', 'icon-button'");
    expect(detailView).not.toContain('class="metrics-row"');
    expect(detailView).not.toContain("reaction-button");
  });

  it("uses compact similar-card markup instead of full feed cards", () => {
    expect(detailView).toContain('class="similar-grid"');
    expect(detailView).toContain("<SimilarVideoCard");
    expect(detailView).not.toContain("<VideoCard");
    expect(similarCard).toContain('class="similar-card-item"');
    expect(similarCard).toContain('class="similar-thumb"');
    expect(similarCard).toContain('class="similar-title"');
  });

  it("keeps video-detail navigation contextual like the old page", () => {
    expect(header).toContain('v-if="!isVideoDetail"');
    expect(header).toContain("#similar-section");
    expect(header).toContain("Similar videos");
  });
});
