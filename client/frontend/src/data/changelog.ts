/**
 * Module `client/frontend/src/data/changelog.ts`: provide runtime functionality.
 */

export type ChangelogEntry = {
  id: string;
  date: string;
  time: string;
  status: ChangelogStatus;
  title: string;
  summary: string;
};

export type ChangelogStatus = "Planned" | "Done";

export type ChangelogSeenState = {
  id: string;
  status: ChangelogStatus | null;
};

type ChangelogPayload = {
  entries?: unknown;
};

export const CHANGELOG_URL =
  "https://raw.githubusercontent.com/denikryt/PeerTube-browser/refs/heads/main/CHANGELOG.json";
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
 * Handle get latest changelog seen state.
 */
export function getLatestChangelogSeenState(entries: ChangelogEntry[]): ChangelogSeenState | null {
  if (!entries.length) return null;
  return { id: entries[0].id, status: entries[0].status };
}

/**
 * Handle read seen changelog state from localStorage.
 * Supports both legacy plain-id value and new JSON {id,status}.
 */
export function readSeenChangelogState(): ChangelogSeenState | null {
  const raw = localStorage.getItem(CHANGELOG_SEEN_ID_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return null;
    const candidate = parsed as Record<string, unknown>;
    const id = normalizeString(candidate.id);
    if (!id) return null;
    return { id, status: normalizeStatus(candidate.status) };
  } catch {
    const id = normalizeString(raw);
    if (!id) return null;
    return { id, status: null };
  }
}

/**
 * Handle write seen changelog state to localStorage.
 */
export function writeSeenChangelogState(state: {
  id: string;
  status: ChangelogStatus;
}): void {
  localStorage.setItem(
    CHANGELOG_SEEN_ID_KEY,
    JSON.stringify({ id: state.id, status: state.status })
  );
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
    const time = normalizeTime(candidate.time);
    const title = normalizeString(candidate.title);
    const summary = normalizeString(candidate.summary);
    if (!date || !title || !summary) continue;
    const id = normalizeString(candidate.id);
    const status = normalizeStatus(candidate.status);
    if (!id || !status) continue;
    if (!isIsoDate(date)) continue;
    normalized.push({ id, date, time: time ?? "00:00:00", status, title, summary });
  }

  normalized.sort((a, b) => {
    const aTimestamp = parseTimestamp(a.date, a.time);
    const bTimestamp = parseTimestamp(b.date, b.time);
    if (aTimestamp !== bTimestamp) {
      return bTimestamp - aTimestamp;
    }
    if (a.date === b.date && a.time === b.time) {
      return a.id.localeCompare(b.id);
    }
    if (a.date !== b.date) {
      return a.date < b.date ? 1 : -1;
    }
    return a.time < b.time ? 1 : -1;
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

/**
 * Normalize optional changelog time (HH:MM:SS).
 */
function normalizeTime(value: unknown): string | null {
  const normalized = normalizeString(value);
  if (!normalized) return null;
  if (!/^\d{2}:\d{2}:\d{2}$/.test(normalized)) return null;
  const [hhRaw, mmRaw, ssRaw] = normalized.split(":");
  const hh = Number(hhRaw);
  const mm = Number(mmRaw);
  const ss = Number(ssRaw);
  if (!Number.isInteger(hh) || !Number.isInteger(mm) || !Number.isInteger(ss)) return null;
  if (hh < 0 || hh > 23) return null;
  if (mm < 0 || mm > 59) return null;
  if (ss < 0 || ss > 59) return null;
  return normalized;
}

/**
 * Convert changelog date+time to unix timestamp for stable sorting.
 */
function parseTimestamp(date: string, time: string): number {
  const parsed = Date.parse(`${date}T${time}Z`);
  if (!Number.isFinite(parsed)) return 0;
  return parsed;
}
