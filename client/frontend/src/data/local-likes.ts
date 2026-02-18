/**
 * Module `client/frontend/src/data/local-likes.ts`: provide runtime functionality.
 */

export type StoredLike = {
  video_uuid: string;
  instance_domain: string;
};

export type RequestLike = {
  uuid: string;
  host: string;
};

const STORAGE_KEY = "localLikes:v1";
const MAX_LIKES = 50;

/**
 * Handle add local like.
 */
export function addLocalLike(videoUuid: string, instanceDomain: string, maxItems = MAX_LIKES) {
  if (!videoUuid || !instanceDomain) return;
  const likes = loadLikes();
  const normalized = normalizeLike({ video_uuid: videoUuid, instance_domain: instanceDomain });
  const filtered = likes.filter(
    (entry) =>
      !(
        entry.video_uuid === normalized.video_uuid &&
        entry.instance_domain === normalized.instance_domain
      )
  );
  filtered.unshift(normalized);
  if (maxItems > 0 && filtered.length > maxItems) {
    filtered.length = maxItems;
  }
  saveLikes(filtered);
}

/**
 * Handle get random likes.
 */
export function getRandomLikes(maxItems = 5): RequestLike[] {
  const likes = loadLikes();
  if (!likes.length) return [];
  const count = Math.min(maxItems > 0 ? maxItems : likes.length, likes.length);
  const shuffled = shuffle([...likes]);
  return shuffled.slice(0, count).map((entry) => ({
    uuid: entry.video_uuid,
    host: entry.instance_domain
  }));
}

/**
 * Handle get stored likes.
 */
export function getStoredLikes(): StoredLike[] {
  return loadLikes();
}

/**
 * Handle clear local likes.
 */
export function clearLocalLikes() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage errors.
  }
}

/**
 * Handle load likes.
 */
function loadLikes(): StoredLike[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((entry) => normalizeLike(entry))
      .filter((entry) => Boolean(entry.video_uuid && entry.instance_domain));
  } catch {
    return [];
  }
}

/**
 * Handle save likes.
 */
function saveLikes(likes: StoredLike[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(likes));
  } catch {
    // Ignore storage errors.
  }
}

/**
 * Handle normalize like.
 */
function normalizeLike(entry: unknown): StoredLike {
  if (!entry || typeof entry !== "object") {
    return { video_uuid: "", instance_domain: "" };
  }
  const record = entry as Record<string, unknown>;
  const videoUuid = String(record.video_uuid ?? record.uuid ?? "").trim();
  const instanceDomain = String(record.instance_domain ?? record.host ?? "").trim();
  return {
    video_uuid: videoUuid,
    instance_domain: instanceDomain
  };
}

function shuffle<T>(items: T[]) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}
