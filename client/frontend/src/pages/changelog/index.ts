/**
 * Module `client/frontend/src/pages/changelog/index.ts`: provide runtime functionality.
 */

import "../../videos.css";
import "../../changelog.css";
import {
  CHANGELOG_URL,
  fetchChangelogEntries,
  getLatestChangelogId,
  readSeenChangelogId,
  writeSeenChangelogId,
  type ChangelogEntry,
  type ChangelogStatus,
} from "../../data/changelog";

const counts = document.getElementById("changelog-counts");
const meta = document.getElementById("changelog-meta");
const state = document.getElementById("changelog-state");
const list = document.getElementById("changelog-list");
const filterTabs = Array.from(
  document.querySelectorAll<HTMLButtonElement>(".changelog-tab[data-status]")
);
const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });
const STATUS_EMPTY_MESSAGES: Record<ChangelogStatus, string> = {
  Planned: "No planned tasks.",
  Done: "No completed tasks yet.",
};

let allEntries: ChangelogEntry[] = [];
let activeStatus: ChangelogStatus = "Planned";
let sessionSeenId: string | null = null;

if (!counts || !meta || !state || !list || filterTabs.length === 0) {
  throw new Error("Missing changelog elements");
}

wireFilterTabs();
void loadChangelog();

/**
 * Handle load changelog.
 */
async function loadChangelog() {
  setLoadingState("Loading changelog...");

  try {
    sessionSeenId = readSeenChangelogId();
    const entries = await fetchChangelogEntries();
    allEntries = entries;
    if (!entries.length) {
      setEmptyState("Changelog is empty.");
      return;
    }

    renderActiveStatus();

    const latestId = getLatestChangelogId(entries);
    if (latestId) {
      writeSeenChangelogId(latestId);
      window.dispatchEvent(new Event("changelog:seen-updated"));
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not load changelog.";
    setErrorState(message);
  }
}

/**
 * Handle wire filter tabs.
 */
function wireFilterTabs() {
  for (const button of filterTabs) {
    const status = parseStatus(button.dataset.status);
    if (!status) continue;
    button.addEventListener("click", () => {
      if (activeStatus === status) return;
      activeStatus = status;
      updateFilterTabState();
      renderActiveStatus();
    });
  }
  updateFilterTabState();
}

/**
 * Handle update filter tab state.
 */
function updateFilterTabState() {
  for (const button of filterTabs) {
    const status = parseStatus(button.dataset.status);
    const isActive = status === activeStatus;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  }
}

/**
 * Handle render active status.
 */
function renderActiveStatus() {
  const visibleEntries = allEntries.filter((entry) => entry.status === activeStatus);
  const unreadEntryIds = buildUnreadEntryIdSet(allEntries, sessionSeenId);
  updateSummary();
  if (!visibleEntries.length) {
    setEmptyState(STATUS_EMPTY_MESSAGES[activeStatus]);
    return;
  }
  renderEntries(visibleEntries, unreadEntryIds);
}

/**
 * Handle render entries.
 */
function renderEntries(entries: ChangelogEntry[], unreadEntryIds: Set<string>) {
  state.hidden = true;
  list.hidden = false;
  list.innerHTML = "";

  const unreadVisibleCount = entries.reduce((count, entry) => {
    return unreadEntryIds.has(entry.id) ? count + 1 : count;
  }, 0);
  const fragment = document.createDocumentFragment();
  for (const [index, entry] of entries.entries()) {
    if (unreadVisibleCount > 0 && unreadVisibleCount < entries.length && index === unreadVisibleCount) {
      fragment.appendChild(renderUnreadDivider());
    }
    fragment.appendChild(renderEntry(entry));
  }
  if (unreadVisibleCount > 0 && unreadVisibleCount === entries.length) {
    fragment.appendChild(renderUnreadDivider());
  }
  list.appendChild(fragment);
}

/**
 * Handle build unread entry id set from latest entries down to seen id.
 */
function buildUnreadEntryIdSet(entries: ChangelogEntry[], seenId: string | null): Set<string> {
  if (!entries.length) return new Set();
  if (!seenId) return new Set(entries.map((entry) => entry.id));
  const seenIndex = entries.findIndex((entry) => entry.id === seenId);
  if (seenIndex <= 0) return new Set();
  if (seenIndex < 0) {
    return new Set(entries.map((entry) => entry.id));
  }
  return new Set(entries.slice(0, seenIndex).map((entry) => entry.id));
}

/**
 * Handle render unread divider.
 */
function renderUnreadDivider(): HTMLElement {
  const divider = document.createElement("div");
  divider.className = "changelog-divider";
  divider.textContent = "New";
  return divider;
}

/**
 * Handle render entry.
 */
function renderEntry(entry: ChangelogEntry): HTMLElement {
  const article = document.createElement("article");
  article.className = `changelog-card ${entry.status === "Done" ? "is-done" : "is-planned"}`;

  const cardHeader = document.createElement("div");
  cardHeader.className = "changelog-card-header";

  const dateNode = document.createElement("p");
  dateNode.className = "changelog-date";
  dateNode.textContent = formatDate(entry.date);

  const statusNode = renderStatusBadge(entry.status);

  const titleNode = document.createElement("h2");
  titleNode.className = "changelog-title";
  titleNode.textContent = entry.title;

  const summaryNode = document.createElement("p");
  summaryNode.className = "changelog-summary";
  summaryNode.textContent = entry.summary;

  cardHeader.appendChild(dateNode);
  cardHeader.appendChild(statusNode);
  article.appendChild(cardHeader);
  article.appendChild(titleNode);
  article.appendChild(summaryNode);
  return article;
}

/**
 * Handle render status badge.
 */
function renderStatusBadge(status: ChangelogStatus): HTMLElement {
  const badge = document.createElement("span");
  badge.className = `changelog-status ${status === "Done" ? "is-done" : "is-planned"}`;
  badge.textContent = status === "Done" ? "✓ Done" : "Planned";
  return badge;
}

/**
 * Handle set loading state.
 */
function setLoadingState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.remove("error");
  state.textContent = message;
  updateSummary();
}

/**
 * Handle set empty state.
 */
function setEmptyState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.remove("error");
  state.textContent = message;
}

/**
 * Handle set error state.
 */
function setErrorState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.add("error");
  state.textContent = message;
  counts.textContent = "Unavailable";
  renderSourceOnlyMeta();
}

/**
 * Handle format date.
 */
function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return dateFormat.format(date);
}

/**
 * Handle update summary.
 */
function updateSummary() {
  const plannedCount = allEntries.filter((entry) => entry.status === "Planned").length;
  const doneCount = allEntries.filter((entry) => entry.status === "Done").length;
  counts.textContent = "";
  renderMeta(
    `Not completed: ${plannedCount} • Completed: ${doneCount}`,
    "Source: "
  );
}

/**
 * Handle render source only meta.
 */
function renderSourceOnlyMeta() {
  renderMeta("", "Source: ");
}

/**
 * Handle render meta.
 */
function renderMeta(statsLine: string, sourcePrefix: string) {
  meta.textContent = "";
  if (statsLine) {
    const stats = document.createElement("span");
    stats.textContent = statsLine;
    meta.appendChild(stats);
    meta.appendChild(document.createElement("br"));
  }
  const sourceText = document.createElement("span");
  sourceText.textContent = sourcePrefix;
  const sourceLink = document.createElement("a");
  sourceLink.href = CHANGELOG_URL;
  sourceLink.textContent = CHANGELOG_URL;
  sourceLink.target = "_blank";
  sourceLink.rel = "noreferrer noopener";
  meta.appendChild(sourceText);
  meta.appendChild(sourceLink);
}

/**
 * Handle parse status.
 */
function parseStatus(value: string | undefined): ChangelogStatus | null {
  if (value === "Planned" || value === "Done") {
    return value;
  }
  return null;
}
