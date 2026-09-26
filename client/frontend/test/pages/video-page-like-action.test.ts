/**
 * Characterization tests for the extracted video-page like action helper.
 */

import { describe, expect, it, vi } from "vitest";
import { handleVideoLikeAction, toggleReaction } from "../../src/state/profile-likes";

describe("video page like action", () => {
  it("preserves visual toggle semantics", () => {
    const like = document.createElement("button");
    const dislike = document.createElement("button");
    dislike.classList.add("active");

    expect(toggleReaction(like, dislike)).toBe(true);
    expect(like.classList.contains("active")).toBe(true);
    expect(dislike.classList.contains("active")).toBe(false);

    expect(toggleReaction(like, dislike)).toBe(false);
    expect(like.classList.contains("active")).toBe(false);
  });

  it("sends the Client action and persists local like identity in the current finally path", async () => {
    const like = document.createElement("button");
    const sendAction = vi.fn().mockResolvedValue(undefined);
    const addLike = vi.fn();

    await handleVideoLikeAction({
      apiBase: "http://127.0.0.1:7172",
      seedId: "seed-id",
      seedHost: "example.org",
      metadata: { videoUuid: "uuid-1", instanceName: "meta.example" },
      likeButton: like,
      sendAction,
      addLike
    });

    expect(sendAction).toHaveBeenCalledWith("http://127.0.0.1:7172", {
      videoId: "seed-id",
      host: "example.org",
      action: "like"
    });
    expect(addLike).toHaveBeenCalledWith("uuid-1", "example.org");
    expect(like.disabled).toBe(false);
  });
});
