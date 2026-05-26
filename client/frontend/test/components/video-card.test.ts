/**
 * Characterization tests for extracted video card rendering helpers.
 */

import { describe, expect, it } from "vitest";
import { renderFeedVideoCard, renderSimilarVideoCard } from "../../src/components/video-card";
import type { VideoRow } from "../../src/types/videos";

const row: VideoRow = {
  video_id: "v1",
  video_uuid: "uuid-1",
  instance_domain: "example.org",
  title: "Example <Video>",
  channel_name: "Example Channel",
  channel_url: "https://example.org/video-channels/example",
  thumbnail_url: "https://example.org/static/thumb.jpg",
  views: 1234,
  likes: 10,
  dislikes: 1,
  duration: 95,
  published_at: 1704067200,
  debug: {
    score: 0.1234,
    similarity_score: 0.5,
    freshness_score: 0.25,
    popularity_score: 0.75,
    layer: "exploit",
    rank_before: 4,
    rank_after: 1
  }
};

describe("video card renderers", () => {
  it("preserves feed card links, classes, stats, escaping, and debug markup", () => {
    const html = renderFeedVideoCard(row, {
      apiParam: "http://127.0.0.1:7172",
      debugMode: true,
      videoKey: "example.org::uuid-1"
    });

    expect(html).toContain('class="video-card"');
    expect(html).toContain('data-video-key="example.org::uuid-1"');
    expect(html).toContain("Example &lt;Video&gt;");
    expect(html).toContain("/video-page.html?");
    expect(html).toContain("api=http%3A%2F%2F127.0.0.1%3A7172");
    expect(html).toContain("Example Channel");
    expect(html).toContain("1,234");
    expect(html).toContain("1:35");
    expect(html).toContain("video-debug");
    expect(html).toContain("exploit");
  });

  it("preserves similar-card markup used by the video page", () => {
    const html = renderSimilarVideoCard(row, { views: 42, videoKey: "example.org::uuid-1" });

    expect(html).toContain('class="similar-card-item"');
    expect(html).toContain('data-video-key="example.org::uuid-1"');
    expect(html).toContain("Example &lt;Video&gt;");
    expect(html).toContain("Example Channel");
    expect(html).toContain("42");
  });
});
