/**
 * Pure behavior tests for canonical PeerTube video metadata normalization.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  CURRENT_VIDEO_METADATA_VERSION,
  extractAccountIdentity,
  extractCategory,
  extractLanguage,
  extractLicence,
  normalizeVideoMetadata
} from "../src/video-metadata.js";

test("identifier helpers accept object, primitive, and null PeerTube shapes", () => {
  assert.deepEqual(extractCategory({ id: 3, label: "Music" }), {
    id: "3",
    label: "Music"
  });
  assert.deepEqual(extractLicence({ identifier: "attribution", name: "Attribution" }), {
    id: "attribution",
    label: "Attribution"
  });
  assert.deepEqual(extractLanguage("en"), { id: "en", label: null });
  assert.deepEqual(extractLanguage(null), { id: null, label: null });
});

test("account identity keeps username separate from display name and canonical URL", () => {
  assert.deepEqual(
    extractAccountIdentity(
      {
        name: "alice",
        displayName: "Alice Example",
        url: "https://video.example/accounts/alice",
        avatar: { path: "/lazy-static/avatars/alice.png" }
      },
      "video.example",
      "https:"
    ),
    {
      username: "alice",
      displayName: "Alice Example",
      url: "https://video.example/accounts/alice",
      avatarUrl: "https://video.example/lazy-static/avatars/alice.png"
    }
  );
});

test("detail metadata wins for a new row and produces metadata version one", () => {
  const normalized = normalizeVideoMetadata({
    listVideo: {
      name: "List title",
      description: "List description",
      tags: ["list"],
      category: { id: 1, label: "List Category" },
      language: { id: "fr", label: "French" }
    },
    detail: {
      name: "Detail title",
      description: "Detail description",
      tags: ["one", "two"],
      category: { id: 3, label: "Music" },
      licence: { id: 2, label: "Attribution" },
      language: { id: "en", label: "English" },
      nsfw: true,
      nsfwSummary: "Content warning",
      publishedAt: "2026-01-02T03:04:05Z",
      originallyPublishedAt: "2025-01-02T03:04:05Z",
      updatedAt: "2026-02-03T04:05:06Z",
      isLive: false,
      aspectRatio: 1.777,
      support: "https://support.example/creator",
      account: {
        name: "alice",
        displayName: "Alice",
        url: "https://video.example/accounts/alice"
      }
    },
    activityPub: null,
    host: "video.example",
    protocol: "https:"
  });

  assert.equal(normalized.title, "Detail title");
  assert.equal(normalized.description, "Detail description");
  assert.equal(normalized.tagsJson, '["one","two"]');
  assert.deepEqual([normalized.categoryId, normalized.category], ["3", "Music"]);
  assert.deepEqual([normalized.licenceId, normalized.licence], ["2", "Attribution"]);
  assert.deepEqual([normalized.language, normalized.languageLabel], ["en", "English"]);
  assert.equal(normalized.nsfw, 1);
  assert.equal(normalized.sensitiveSummary, "Content warning");
  assert.equal(normalized.originallyPublishedAt, Date.parse("2025-01-02T03:04:05Z"));
  assert.equal(normalized.updatedAt, Date.parse("2026-02-03T04:05:06Z"));
  assert.equal(normalized.isLive, 0);
  assert.equal(normalized.aspectRatio, 1.777);
  assert.equal(normalized.support, "https://support.example/creator");
  assert.equal(normalized.accountUsername, "alice");
  assert.equal(normalized.accountName, "Alice");
  assert.equal(normalized.metadataVersion, CURRENT_VIDEO_METADATA_VERSION);
});

test("live video remains incomplete until public live parity fields are known", () => {
  const incomplete = normalizeVideoMetadata({
    listVideo: { isLive: true },
    detail: { isLive: true },
    activityPub: null,
    host: "video.example",
    protocol: "https:"
  });
  assert.equal(incomplete.metadataVersion, 0);

  const complete = normalizeVideoMetadata({
    listVideo: { isLive: true },
    detail: { isLive: true },
    activityPub: { permanentLive: true, liveSaveReplay: false },
    host: "video.example",
    protocol: "https:"
  });
  assert.equal(complete.permanentLive, 1);
  assert.equal(complete.liveSaveReplay, 0);
  assert.equal(complete.metadataVersion, CURRENT_VIDEO_METADATA_VERSION);
});

test("unknown optional values remain nullable without inventing false values", () => {
  const normalized = normalizeVideoMetadata({
    listVideo: {},
    detail: { isLive: null, permanentLive: null, liveSaveReplay: null },
    activityPub: null,
    host: "video.example",
    protocol: "https:"
  });

  assert.equal(normalized.isLive, null);
  assert.equal(normalized.permanentLive, null);
  assert.equal(normalized.liveSaveReplay, null);
  assert.equal(normalized.metadataVersion, CURRENT_VIDEO_METADATA_VERSION);
});
