/**
 * Profile modal rendering helpers extracted from the videos page.
 */

import type { VideoRow } from "../types/videos";
import { escapeHtml } from "../utils/format";
import { channelName, thumbnailUrl, videoPageUrl } from "../utils/video-fields";

/** Render the existing profile likes card markup used by the videos page modal. */
export function renderProfileLikes(likes: VideoRow[], apiParam?: string | null) {
  if (!likes.length) {
    return `<div class="empty">No likes yet.</div>`;
  }
  return likes
    .map((row) => {
      const title = row.title ?? "Untitled";
      const thumb = thumbnailUrl(row);
      const link = videoPageUrl(row, apiParam);
      const channel = channelName(row);
      const host = row.instance_domain ?? row.instanceDomain ?? "";
      const meta = host ? `${channel} · ${host}` : channel;
      const thumbMarkup = thumb
        ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
        : `<div class="thumb-fallback">No preview</div>`;
      return `
        <a class="like-card" href="${escapeHtml(link)}">
          <div class="like-thumb">${thumbMarkup}</div>
          <h3 class="like-title">${escapeHtml(title)}</h3>
          <div class="like-meta">${escapeHtml(meta)}</div>
        </a>
      `;
    })
    .join("");
}
