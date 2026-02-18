/**
 * Module `client/frontend/src/pages/changelog/index.ts`: provide runtime functionality.
 */

import "../../videos.css";
import "../../changelog.css";
import {
  CHANGELOG_URL,
  countUnseenEntries,
  fetchChangelogEntries,
  getLatestChangelogId,
  readSeenChangelogId,
  writeSeenChangelogId,
  type ChangelogEntry,
} from "../../data/changelog";

const counts = document.getElementById("changelog-counts");
const meta = document.getElementById("changelog-meta");
const state = document.getElementById("changelog-state");
const list = document.getElementById("changelog-list");
const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });

if (!counts || !meta || !state || !list) {
  throw new Error("Missing changelog elements");
}

void loadChangelog();

/**
 * Handle load changelog.
 */
async function loadChangelog() {
  setLoadingState("Loading changelog...");

  try {
    const entries = await fetchChangelogEntries();
    if (!entries.length) {
      setEmptyState("Changelog is empty.");
      return;
    }

    const previousSeenId = readSeenChangelogId();
    const unseenCount = countUnseenEntries(entries, previousSeenId);
    renderEntries(entries, unseenCount);

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
 * Handle render entries.
 */
function renderEntries(entries: ChangelogEntry[], unseenCount: number) {
  state.hidden = true;
  list.hidden = false;
  list.innerHTML = "";

  const fragment = document.createDocumentFragment();
  for (const [index, entry] of entries.entries()) {
    if (index === unseenCount && unseenCount > 0 && unseenCount < entries.length) {
      fragment.appendChild(renderSeenSeparator());
    }
    fragment.appendChild(renderEntry(entry, index < unseenCount));
  }
  list.appendChild(fragment);

  counts.textContent = `Showing ${entries.length} updates`;
  meta.textContent = "";
}

/**
 * Handle render entry.
 */
function renderEntry(entry: ChangelogEntry, isNew: boolean): HTMLElement {
  const article = document.createElement("article");
  article.className = `changelog-card${isNew ? " is-new" : ""}`;

  const dateNode = document.createElement("p");
  dateNode.className = "changelog-date";
  dateNode.textContent = formatDate(entry.date);

  const titleNode = document.createElement("h2");
  titleNode.className = "changelog-title";
  titleNode.textContent = entry.title;

  const summaryNode = document.createElement("p");
  summaryNode.className = "changelog-summary";
  summaryNode.textContent = entry.summary;

  article.appendChild(dateNode);
  article.appendChild(titleNode);
  article.appendChild(summaryNode);
  return article;
}

/**
 * Handle render seen separator.
 */
function renderSeenSeparator(): HTMLElement {
  const separator = document.createElement("div");
  separator.className = "changelog-separator";
  separator.textContent = "Previously seen";
  return separator;
}

/**
 * Handle set loading state.
 */
function setLoadingState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.remove("error");
  state.textContent = message;
  counts.textContent = "";
  meta.textContent = "";
}

/**
 * Handle set empty state.
 */
function setEmptyState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.remove("error");
  state.textContent = message;
  counts.textContent = "No updates";
  meta.textContent = "";
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
  meta.textContent = "";
}

/**
 * Handle format date.
 */
function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return dateFormat.format(date);
}
