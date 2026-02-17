import type { VideoRow } from "../types/videos";
import { getStoredLikes } from "./local-likes";
import { resolveClientApiBase } from "./api-base";

interface UserProfileResponse {
  user_id?: string;
  likes?: VideoRow[];
}

const USE_LOCAL_LIKES_PROFILE = true;

export async function fetchUserProfileLikes(apiBase: string): Promise<VideoRow[]> {
  const clientApiBase = resolveClientApiBase(apiBase);
  if (USE_LOCAL_LIKES_PROFILE) {
    const stored = getStoredLikes();
    if (!stored.length) return [];
    const response = await fetch(new URL("/api/user-profile/likes", clientApiBase), {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        likes: stored.map((entry) => ({
          uuid: entry.video_uuid,
          host: entry.instance_domain
        }))
      })
    });
    if (!response.ok) {
      const message = await readErrorMessage(response);
      throw new Error(message ?? "Failed to fetch user profile");
    }
    const payload = (await response.json()) as UserProfileResponse;
    return Array.isArray(payload.likes) ? payload.likes : [];
  }

  const response = await fetch(new URL("/api/user-profile/likes", clientApiBase));
  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(message ?? "Failed to fetch user profile");
  }
  const payload = (await response.json()) as UserProfileResponse;
  return Array.isArray(payload.likes) ? payload.likes : [];
}

export async function resetUserProfileLikes(apiBase: string): Promise<VideoRow[]> {
  const clientApiBase = resolveClientApiBase(apiBase);
  const response = await fetch(new URL("/api/user-profile/reset", clientApiBase), {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({})
  });
  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(message ?? "Failed to reset user profile");
  }
  const payload = (await response.json()) as UserProfileResponse;
  return Array.isArray(payload.likes) ? payload.likes : [];
}

async function readErrorMessage(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { error?: string };
    return payload.error ?? null;
  } catch {
    return null;
  }
}
