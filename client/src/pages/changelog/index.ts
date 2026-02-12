import "../../videos.css";
import "../../changelog.css";

type ChangelogEntry = {
  date: string;
  title: string;
  summary: string;
};

type ChangelogPayload = {
  entries?: unknown;
};

const CHANGELOG_URL = "https://raw.githubusercontent.com/denikryt/PeerTube-Browser/main/CHANGELOG.json";

const counts = document.getElementById("changelog-counts");
const meta = document.getElementById("changelog-meta");
const state = document.getElementById("changelog-state");
const list = document.getElementById("changelog-list");
const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });

if (!counts || !meta || !state || !list) {
  throw new Error("Missing changelog elements");
}

void loadChangelog();

async function loadChangelog() {
  setLoadingState("Loading changelog...");

  try {
    const response = await fetch(CHANGELOG_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Could not load changelog (HTTP ${response.status}).`);
    }

    const payload = (await response.json()) as unknown;
    const entries = normalizeEntries(payload);
    if (!entries.length) {
      setEmptyState("Changelog is empty.");
      return;
    }

    renderEntries(entries);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not load changelog.";
    setErrorState(message);
  }
}

function normalizeEntries(payload: unknown): ChangelogEntry[] {
  const rawList = extractRawEntries(payload);
  const normalized: ChangelogEntry[] = [];

  for (const item of rawList) {
    if (!item || typeof item !== "object") continue;
    const candidate = item as Record<string, unknown>;
    const date = normalizeString(candidate.date);
    const title = normalizeString(candidate.title);
    const summary = normalizeString(candidate.summary);
    if (!date || !title || !summary) continue;
    if (!isIsoDate(date)) continue;
    normalized.push({ date, title, summary });
  }

  normalized.sort((a, b) => {
    if (a.date === b.date) return 0;
    return a.date < b.date ? 1 : -1;
  });
  return normalized;
}

function extractRawEntries(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  const container = payload as ChangelogPayload;
  if (!Array.isArray(container.entries)) return [];
  return container.entries;
}

function normalizeString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.trim();
  return cleaned.length ? cleaned : null;
}

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(parsed);
}

function renderEntries(entries: ChangelogEntry[]) {
  state.hidden = true;
  list.hidden = false;
  list.innerHTML = "";

  const fragment = document.createDocumentFragment();
  for (const entry of entries) {
    fragment.appendChild(renderEntry(entry));
  }
  list.appendChild(fragment);

  counts.textContent = `Showing ${entries.length} updates`;
  meta.textContent = "";
}

function renderEntry(entry: ChangelogEntry): HTMLElement {
  const article = document.createElement("article");
  article.className = "changelog-card";

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

function setLoadingState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.remove("error");
  state.textContent = message;
  counts.textContent = "";
  meta.textContent = "";
}

function setEmptyState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.remove("error");
  state.textContent = message;
  counts.textContent = "No updates";
  meta.textContent = "";
}

function setErrorState(message: string) {
  list.hidden = true;
  state.hidden = false;
  state.classList.add("error");
  state.textContent = message;
  counts.textContent = "Unavailable";
  meta.textContent = "";
}

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return dateFormat.format(date);
}
