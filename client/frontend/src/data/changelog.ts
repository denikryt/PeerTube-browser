/**
 * Module `client/frontend/src/data/changelog.ts`: provide runtime functionality.
 */

export type ChangelogEntry = {
  id: string;
  date: string;
  status: ChangelogStatus;
  title: string;
  summary: string;
};

export type ChangelogStatus = "Planned" | "Done";

type ChangelogPayload = {
  entries?: unknown;
};

export const CHANGELOG_URL =
  "https://raw.githubusercontent.com/denikryt/PeerTube-Browser/main/CHANGELOG.json";
export const CHANGELOG_SEEN_ID_KEY = "changelog_seen_id";

/**
 * Handle fetch changelog entries.
 */
export async function fetchChangelogEntries(): Promise<ChangelogEntry[]> {
  const response = await fetch(CHANGELOG_URL, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load changelog (HTTP ${response.status}).`);
  }
  const payload = (await response.json()) as unknown;
  return normalizeEntries(payload);
}

/**
 * Handle get latest changelog id.
 */
export function getLatestChangelogId(entries: ChangelogEntry[]): string | null {
  if (!entries.length) return null;
  return entries[0].id;
}

/**
 * Handle read seen changelog id.
 */
export function readSeenChangelogId(): string | null {
  return localStorage.getItem(CHANGELOG_SEEN_ID_KEY);
}

/**
 * Handle write seen changelog id.
 */
export function writeSeenChangelogId(id: string): void {
  localStorage.setItem(CHANGELOG_SEEN_ID_KEY, id);
}

/**
 * Handle normalize entries.
 */
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
    const id = normalizeString(candidate.id);
    const status = normalizeStatus(candidate.status);
    if (!id || !status) continue;
    if (!isIsoDate(date)) continue;
    normalized.push({ id, date, status, title, summary });
  }

  normalized.sort((a, b) => {
    if (a.date === b.date) {
      return a.id.localeCompare(b.id);
    }
    return a.date < b.date ? 1 : -1;
  });
  return normalized;
}

/**
 * Handle extract raw entries.
 */
function extractRawEntries(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  const container = payload as ChangelogPayload;
  if (!Array.isArray(container.entries)) return [];
  return container.entries;
}

/**
 * Handle normalize string.
 */
function normalizeString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.trim();
  return cleaned.length ? cleaned : null;
}

/**
 * Handle normalize status.
 */
function normalizeStatus(value: unknown): ChangelogStatus | null {
  const normalized = normalizeString(value);
  if (!normalized) return null;
  if (normalized === "Planned" || normalized === "Done") {
    return normalized;
  }
  return null;
}

/**
 * Check whether is iso date.
 */
function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(parsed);
}
