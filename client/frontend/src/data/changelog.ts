export type ChangelogEntry = {
  date: string;
  title: string;
  summary: string;
};

type ChangelogPayload = {
  entries?: unknown;
};

export const CHANGELOG_URL =
  "https://raw.githubusercontent.com/denikryt/PeerTube-Browser/main/CHANGELOG.json";
export const CHANGELOG_SEEN_ID_KEY = "changelog_seen_id";

export async function fetchChangelogEntries(): Promise<ChangelogEntry[]> {
  const response = await fetch(CHANGELOG_URL, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load changelog (HTTP ${response.status}).`);
  }
  const payload = (await response.json()) as unknown;
  return normalizeEntries(payload);
}

export function makeChangelogEntryId(entry: ChangelogEntry): string {
  return `${entry.date}|${entry.title}`;
}

export function getLatestChangelogId(entries: ChangelogEntry[]): string | null {
  if (!entries.length) return null;
  return makeChangelogEntryId(entries[0]);
}

export function readSeenChangelogId(): string | null {
  return localStorage.getItem(CHANGELOG_SEEN_ID_KEY);
}

export function writeSeenChangelogId(id: string): void {
  localStorage.setItem(CHANGELOG_SEEN_ID_KEY, id);
}

export function countUnseenEntries(
  entries: ChangelogEntry[],
  seenId: string | null
): number {
  if (!entries.length) return 0;
  if (!seenId) return entries.length;
  const seenIndex = entries.findIndex((entry) => makeChangelogEntryId(entry) === seenId);
  if (seenIndex < 0) return entries.length;
  return seenIndex;
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
