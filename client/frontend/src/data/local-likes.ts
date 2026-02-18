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

type LocalLikesPayload = {
  likes?: unknown;
};

type LocalLikesDebugApi = {
  readRaw: () => string | null;
  readArray: () => StoredLike[];
};

const STORAGE_KEY = "localLikes:v1";
const MAX_LIKES = 50;

declare global {
  interface Window {
    __peerTubeLocalLikes?: LocalLikesDebugApi;
  }
}

installLocalLikesDebugHelper();

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
 * Handle read local-likes storage as normalized array.
 */
export function readLocalLikesStorageArray(): StoredLike[] {
  return parseLocalLikesStorageValue(readLocalLikesStorageRaw());
}

/**
 * Handle read local-likes raw storage value.
 */
export function readLocalLikesStorageRaw(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
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
 * Handle parse local-likes storage value to normalized array.
 */
export function parseLocalLikesStorageValue(raw: string | null): StoredLike[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return normalizeLikesList(parsed);
    }
    if (parsed && typeof parsed === "object") {
      const payload = parsed as LocalLikesPayload;
      if (Array.isArray(payload.likes)) {
        return normalizeLikesList(payload.likes);
      }
    }
    return [];
  } catch {
    return [];
  }
}

/**
 * Handle expose local-likes debug helper in browser runtime.
 */
function installLocalLikesDebugHelper() {
  if (typeof window === "undefined") return;
  window.__peerTubeLocalLikes = {
    readRaw: () => readLocalLikesStorageRaw(),
    readArray: () => readLocalLikesStorageArray()
  };
}

/**
 * Handle load likes.
 */
function loadLikes(): StoredLike[] {
  return parseLocalLikesStorageValue(readLocalLikesStorageRaw());
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
 * Handle normalize likes list.
 */
function normalizeLikesList(list: unknown[]): StoredLike[] {
  return list
    .map((entry) => normalizeLike(entry))
    .filter((entry) => Boolean(entry.video_uuid && entry.instance_domain));
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
