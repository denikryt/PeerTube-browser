/**
 * Channel table row renderer extracted from the channels page.
 */

import type { ChannelRow } from "../types/channels";
import { escapeHtml } from "../utils/format";

export type ChannelRowRenderOptions = {
  dateFormat?: Intl.DateTimeFormat;
  numberFormat?: Intl.NumberFormat;
};

/** Render the existing six-column channels table row markup. */
export function renderChannelTableRow(row: ChannelRow, options: ChannelRowRenderOptions = {}) {
  const dateFormat = options.dateFormat ?? new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });
  const numberFormat = options.numberFormat ?? new Intl.NumberFormat("en-US");
  const url = channelUrl(row);
  const label = channelLabel(row);
  const followers = row.followers_count ?? 0;
  const videos = row.videos_count ?? 0;
  const checked = row.health_checked_at ? dateFormat.format(new Date(row.health_checked_at)) : "—";
  const errorTag = row.last_error
    ? `<span class="pill">${row.last_error_source === "videos_count" ? "count error" : "error"}</span>`
    : "";
  const avatar = row.avatar_url
    ? `<img class="avatar" src="${escapeHtml(row.avatar_url)}" alt="" loading="lazy" />`
    : `<div class="avatar-fallback">—</div>`;
  return `
        <tr>
          <td class="avatar-cell">${avatar}</td>
          <td>
            <div class="channel-cell">
              <a class="channel-name" href="${url}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>
              <div class="channel-meta">${escapeHtml(row.instance_domain ?? "")} ${errorTag}</div>
            </div>
          </td>
          <td>${escapeHtml(row.instance_domain ?? "—")}</td>
          <td class="num">${numberFormat.format(videos)}</td>
          <td class="num">${numberFormat.format(followers)}</td>
          <td class="num">${checked}</td>
        </tr>
      `;
}

/** Resolve the current channel label fallback order. */
export function channelLabel(row: ChannelRow) {
  return row.display_name ?? row.channel_name ?? row.channel_id ?? "unknown";
}

/** Resolve the current channel URL fallback. */
export function channelUrl(row: ChannelRow) {
  if (row.channel_url) return row.channel_url;
  if (row.channel_name && row.instance_domain) {
    return `https://${row.instance_domain}/video-channels/${encodeURIComponent(row.channel_name)}`;
  }
  return "#";
}
