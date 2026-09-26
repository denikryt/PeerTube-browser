/**
 * Characterization tests for extracted channel table row rendering.
 */

import { describe, expect, it } from "vitest";
import { renderChannelTableRow } from "../../src/components/channel-row";
import type { ChannelRow } from "../../src/types/channels";

const row: ChannelRow = {
  channel_id: "channel-1",
  channel_name: "example_channel",
  display_name: "Example Channel",
  instance_domain: "example.org",
  channel_url: null,
  avatar_url: "https://example.org/avatar.png",
  followers_count: 1234,
  videos_count: 56,
  health_checked_at: 1704067200000,
  last_error: "timeout",
  last_error_source: "videos_count"
};

describe("channel row renderer", () => {
  it("preserves cell order, links, numeric formatting, and error tag", () => {
    const html = renderChannelTableRow(row, {
      dateFormat: new Intl.DateTimeFormat("en-US", { timeZone: "UTC", dateStyle: "medium" })
    });

    expect(html).toContain('class="avatar-cell"');
    expect(html).toContain('href="https://example.org/video-channels/example_channel"');
    expect(html).toContain("Example Channel");
    expect(html).toContain("example.org");
    expect(html).toContain('class="num">56</td>');
    expect(html).toContain('class="num">1,234</td>');
    expect(html).toContain("count error");
  });
});
