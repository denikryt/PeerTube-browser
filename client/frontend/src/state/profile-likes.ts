/**
 * Video-page like action helpers that preserve current local visual/storage behavior.
 */

import { addLocalLike } from "../data/local-likes";
import { sendUserAction } from "../data/user-actions";

export type LikeMetadata = {
  videoUuid?: string | null;
  instanceName?: string | null;
};

export type VideoLikeActionInput = {
  apiBase: string;
  seedId: string | null;
  seedHost: string | null;
  metadata: LikeMetadata | null;
  likeButton: HTMLButtonElement;
  sendAction?: typeof sendUserAction;
  addLike?: typeof addLocalLike;
};

/** Toggle reaction buttons with the current single-active-button behavior. */
export function toggleReaction(active: HTMLButtonElement, other: HTMLButtonElement) {
  const wasActive = active.classList.contains("active");
  active.classList.toggle("active", !wasActive);
  if (!wasActive) {
    other.classList.remove("active");
  }
  return !wasActive;
}

/** Send the current like action and persist local identity in the same finally block. */
export async function handleVideoLikeAction(input: VideoLikeActionInput) {
  if (!input.seedId) return;
  input.likeButton.disabled = true;
  const sendAction = input.sendAction ?? sendUserAction;
  const addLike = input.addLike ?? addLocalLike;
  try {
    await sendAction(input.apiBase, {
      videoId: input.seedId,
      host: input.seedHost,
      action: "like"
    });
  } catch (error) {
    console.warn("[video] failed to send action", error);
  } finally {
    const uuid = resolveLikeUuid(input.seedId, input.metadata);
    const host = resolveLikeHost(input.seedHost, input.metadata);
    if (uuid && host) {
      addLike(uuid, host);
    }
    input.likeButton.disabled = false;
  }
}

/** Resolve like UUID with the current metadata-first fallback. */
export function resolveLikeUuid(id: string, metadata: LikeMetadata | null) {
  const candidate = metadata?.videoUuid ?? "";
  if (candidate) return candidate;
  return looksLikeUuid(id) ? id : "";
}

/** Resolve like host with the current query-param-first fallback. */
export function resolveLikeHost(hostParam: string | null, metadata: LikeMetadata | null) {
  const host = hostParam?.trim();
  if (host) return host;
  const metaHost = metadata?.instanceName?.trim();
  if (metaHost) return metaHost;
  return "";
}

/** Preserve the current loose UUID shape check used by the video page. */
export function looksLikeUuid(value: string) {
  return /^[0-9a-fA-F-]{32,36}$/.test(value);
}
