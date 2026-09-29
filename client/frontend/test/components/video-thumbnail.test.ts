/**
 * Behavioral regression tests for sequential thumbnail fallback.
 */
import { createApp, h, nextTick, reactive } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import VideoThumbnail from "../../src/components/VideoThumbnail.vue";
import type { ThumbnailCandidate } from "../../src/types/videos";
import { resetThumbnailRequestScheduleForTests } from "../../src/utils/thumbnail-request-scheduler";

const DEFAULT_THUMBNAIL_URL = "/default-video-thumbnail.svg";
const mounted: Array<() => void> = [];

/** Mount the real component around reactive URL props for lifecycle assertions. */
function mountThumbnail(initialUrls: string[]) {
  const state = reactive({ urls: initialUrls });
  const root = document.createElement("div");
  document.body.appendChild(root);
  const app = createApp({
    setup() {
      return () => h(VideoThumbnail, { urls: state.urls, alt: "Example video" });
    }
  });
  app.mount(root);
  const cleanup = () => {
    app.unmount();
    root.remove();
  };
  mounted.push(cleanup);
  return { root, state };
}

/** Mount the component with full candidate metadata to verify browser selection policy. */
function mountCandidates(initialCandidates: ThumbnailCandidate[]) {
  const state = reactive({ candidates: initialCandidates });
  const root = document.createElement("div");
  document.body.appendChild(root);
  const app = createApp({
    setup() {
      return () => h(VideoThumbnail, { candidates: state.candidates, alt: "Example video" });
    }
  });
  app.mount(root);
  const cleanup = () => {
    app.unmount();
    root.remove();
  };
  mounted.push(cleanup);
  return { root, state };
}

/** Return the component's single rendered image and reject speculative preload nodes. */
function image(root: HTMLElement) {
  const elements = root.querySelectorAll("img");
  expect(elements).toHaveLength(1);
  return elements[0] as HTMLImageElement;
}

afterEach(() => {
  while (mounted.length) mounted.pop()?.();
  resetThumbnailRequestScheduleForTests();
  vi.useRealTimers();
});

describe("VideoThumbnail", () => {
  it("spaces initial image requests to the same host by 500 milliseconds", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T12:00:00Z"));
    const first = mountCandidates([{ url: "https://img.example/first.jpg", width: 850, height: 480 }]);
    const second = mountCandidates([{ url: "https://img.example/second.jpg", width: 850, height: 480 }]);

    expect(image(first.root).getAttribute("src")).toBe("https://img.example/first.jpg");
    expect(image(second.root).getAttribute("src")).toBe(DEFAULT_THUMBNAIL_URL);
    await vi.advanceTimersByTimeAsync(499);
    expect(image(second.root).getAttribute("src")).toBe(DEFAULT_THUMBNAIL_URL);
    await vi.advanceTimersByTimeAsync(1);
    expect(image(second.root).getAttribute("src")).toBe("https://img.example/second.jpg");
  });

  it("chooses the smallest candidate at least 500 by 300 and keeps the rest for fallback", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T12:00:00Z"));
    const { root } = mountCandidates([
      { url: "https://img.example/large.jpg", width: 1920, height: 1080 },
      { url: "https://img.example/medium.jpg", width: 850, height: 480 },
      { url: "https://img.example/small.jpg", width: 280, height: 157 },
    ]);

    expect(image(root).getAttribute("src")).toBe("https://img.example/medium.jpg");
    image(root).dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(500);
    expect(image(root).getAttribute("src")).toBe("https://img.example/large.jpg");
  });

  it("uses the largest available candidate when none reaches 500 by 300", () => {
    const { root } = mountCandidates([
      { url: "https://img.example/small.jpg", width: 280, height: 157 },
      { url: "https://img.example/tiny.jpg", width: 223, height: 122 },
    ]);

    expect(image(root).getAttribute("src")).toBe("https://img.example/small.jpg");
  });

  it("renders only the first candidate until an error advances the sequence", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T12:00:00Z"));
    const { root } = mountThumbnail(["https://img.example/a.jpg", "https://img.example/b.jpg", "https://img.example/c.jpg"]);

    expect(image(root).getAttribute("src")).toBe("https://img.example/a.jpg");
    image(root).dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(500);
    expect(image(root).getAttribute("src")).toBe("https://img.example/b.jpg");
    expect(root.innerHTML).not.toContain("https://img.example/c.jpg");
  });

  it("keeps a successful first candidate without advancing", async () => {
    const { root } = mountThumbnail(["https://img.example/a.jpg", "https://img.example/b.jpg"]);

    image(root).dispatchEvent(new Event("load"));
    await nextTick();
    expect(image(root).getAttribute("src")).toBe("https://img.example/a.jpg");
  });

  it("falls through every failed remote candidate to the local default", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T12:00:00Z"));
    const { root } = mountThumbnail(["https://img.example/a.jpg", "https://img.example/b.jpg", "https://img.example/c.jpg"]);

    for (const expected of ["https://img.example/b.jpg", "https://img.example/c.jpg"]) {
      image(root).dispatchEvent(new Event("error"));
      await vi.advanceTimersByTimeAsync(500);
      expect(image(root).getAttribute("src")).toBe(expected);
    }
    image(root).dispatchEvent(new Event("error"));
    await nextTick();
    expect(image(root).getAttribute("src")).toBe(DEFAULT_THUMBNAIL_URL);
  });

  it("uses the local default immediately for an empty candidate list", () => {
    const { root } = mountThumbnail([]);
    expect(image(root).getAttribute("src")).toBe(DEFAULT_THUMBNAIL_URL);
  });

  it("does not loop when the local default image errors", async () => {
    const { root } = mountThumbnail([]);
    image(root).dispatchEvent(new Event("error"));
    await nextTick();
    expect(image(root).getAttribute("src")).toBe(DEFAULT_THUMBNAIL_URL);
  });

  it("resets to the first candidate when the URL list changes", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T12:00:00Z"));
    const { root, state } = mountThumbnail(["https://img.example/a.jpg", "https://img.example/b.jpg"]);
    image(root).dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(500);
    expect(image(root).getAttribute("src")).toBe("https://img.example/b.jpg");

    state.urls = ["https://img.example/new-a.jpg", "https://img.example/new-b.jpg"];
    await vi.advanceTimersByTimeAsync(500);
    expect(image(root).getAttribute("src")).toBe("https://img.example/new-a.jpg");
  });
});
