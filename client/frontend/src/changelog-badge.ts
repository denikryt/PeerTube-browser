/**
 * Module `client/frontend/src/changelog-badge.ts`: provide runtime functionality.
 */

import {
  fetchChangelogEntries,
  getLatestChangelogId,
  readSeenChangelogId,
} from "./data/changelog";

const CHANGELOG_LINK_SELECTOR = 'a.nav-link[href="/changelog.html"]';

void refreshChangelogBadge();
window.addEventListener("changelog:seen-updated", () => {
  updateBadgeVisibility(false);
});

/**
 * Handle refresh changelog badge.
 */
async function refreshChangelogBadge() {
  const links = getChangelogLinks();
  if (!links.length) return;

  try {
    const entries = await fetchChangelogEntries();
    const latestId = getLatestChangelogId(entries);
    if (!latestId) {
      updateBadgeVisibility(false);
      return;
    }
    const seenId = readSeenChangelogId();
    updateBadgeVisibility(seenId !== latestId);
  } catch {
    updateBadgeVisibility(false);
  }
}

/**
 * Handle get changelog links.
 */
function getChangelogLinks(): HTMLAnchorElement[] {
  return Array.from(
    document.querySelectorAll<HTMLAnchorElement>(CHANGELOG_LINK_SELECTOR)
  );
}

/**
 * Handle update badge visibility.
 */
function updateBadgeVisibility(show: boolean) {
  const links = getChangelogLinks();
  for (const link of links) {
    if (show) {
      link.classList.add("has-unread-changelog");
      if (!link.querySelector(".changelog-badge")) {
        const dot = document.createElement("span");
        dot.className = "changelog-badge";
        dot.setAttribute("aria-hidden", "true");
        link.appendChild(dot);
      }
    } else {
      link.classList.remove("has-unread-changelog");
      link.querySelector(".changelog-badge")?.remove();
    }
  }
}
