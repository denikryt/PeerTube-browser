/**
 * Canonical PeerTube video metadata normalization.
 *
 * This module converts REST/detail and small ActivityPub enrichment payloads
 * into storage-ready values. It deliberately owns no SQLite or network access
 * so source mapping can be tested independently from crawl orchestration.
 */

import { resolvePeerTubeMediaUrl } from "./video-media.js";

export const CURRENT_VIDEO_METADATA_VERSION = 1;

export interface IdentifierLabel {
  id: string | null;
  label: string | null;
}

export interface AccountIdentity {
  username: string | null;
  displayName: string | null;
  url: string | null;
  avatarUrl: string | null;
}

export interface NormalizedVideoMetadata {
  title: string | null;
  description: string | null;
  tagsJson: string | null;
  categoryId: string | null;
  category: string | null;
  licenceId: string | null;
  licence: string | null;
  language: string | null;
  languageLabel: string | null;
  nsfw: number | null;
  sensitiveSummary: string | null;
  publishedAt: number | null;
  originallyPublishedAt: number | null;
  updatedAt: number | null;
  isLive: number | null;
  permanentLive: number | null;
  liveSaveReplay: number | null;
  aspectRatio: number | null;
  support: string | null;
  accountUsername: string | null;
  accountName: string | null;
  accountUrl: string | null;
  accountAvatarUrl: string | null;
  metadataVersion: number;
}

export interface NormalizeVideoMetadataInput {
  listVideo: Record<string, unknown>;
  /** Successful detail payload; absence means no detail enrichment is trusted. */
  detail?: Record<string, unknown> | null;
  /** Successful public ActivityPub payload used only for missing live fields. */
  activityPub?: Record<string, unknown> | null;
  host: string;
  protocol: string;
}

/** Normalize a PeerTube category identifier/label pair. */
export function extractCategory(value: unknown): IdentifierLabel {
  return extractIdentifierAndLabel(value);
}

/** Normalize a PeerTube licence identifier/label pair. */
export function extractLicence(value: unknown): IdentifierLabel {
  return extractIdentifierAndLabel(value);
}

/** Normalize a PeerTube language identifier/label pair. */
export function extractLanguage(value: unknown): IdentifierLabel {
  return extractIdentifierAndLabel(value);
}

/** Return the stable identifier from PeerTube object or primitive shapes. */
export function extractIdentifier(value: unknown): string | null {
  if (typeof value === "string") return nonBlank(value);
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  return toStringId(record.id ?? record.identifier);
}

/** Return a display label from PeerTube object shapes without fabricating one. */
export function extractDisplayLabel(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  return toNullableString(record.label ?? record.name ?? record.displayName ?? record.display_name);
}

/**
 * Normalize PeerTube Person/account identity while preserving username/display
 * name separation required by future ActivityPub-aligned presentation.
 */
export function extractAccountIdentity(
  value: unknown,
  host: string,
  protocol: string
): AccountIdentity {
  if (!value || typeof value !== "object") {
    return { username: null, displayName: null, url: null, avatarUrl: null };
  }
  const record = value as Record<string, unknown>;
  const avatarSource = firstMediaCandidate(record.avatars) ?? record.avatar ?? record.avatarUrl;
  return {
    username: toNullableString(record.name ?? record.preferredUsername),
    displayName: toNullableString(record.displayName ?? record.display_name),
    url: toNullableString(record.url ?? record.id),
    avatarUrl: resolvePeerTubeMediaUrl(avatarSource, host, protocol)
  };
}

/**
 * Normalize the product-facing metadata subset from list/detail payloads and
 * optional public ActivityPub live enrichment.
 */
export function normalizeVideoMetadata(
  input: NormalizeVideoMetadataInput
): NormalizedVideoMetadata {
  const detail = input.detail ?? null;
  const source = detail ?? input.listVideo;
  const category = extractCategory(source.category ?? input.listVideo.category);
  const licence = extractLicence(source.licence ?? source.license ?? input.listVideo.licence);
  const language = extractLanguage(source.language ?? input.listVideo.language);
  const accountSource =
    source.account ??
    accountFromChannel(source.channel) ??
    input.listVideo.account ??
    accountFromChannel(input.listVideo.channel);
  const account = extractAccountIdentity(accountSource, input.host, input.protocol);
  const activityPub = input.activityPub ?? null;

  const isLive = toNullableBoolean(source.isLive ?? source.is_live ?? input.listVideo.isLive);
  const permanentLive = toNullableBoolean(
    source.permanentLive ?? source.permanent_live ?? activityPub?.permanentLive
  );
  const liveSaveReplay = toNullableBoolean(
    source.liveSaveReplay ?? source.live_save_replay ?? activityPub?.liveSaveReplay
  );

  // Detail acquisition is the completion boundary. Live rows additionally need
  // both public live-parity booleans; non-live/unknown-live rows may legitimately
  // keep optional values null and still be complete.
  const metadataVersion =
    detail !== null &&
    (isLive !== 1 || (permanentLive !== null && liveSaveReplay !== null))
      ? CURRENT_VIDEO_METADATA_VERSION
      : 0;

  return {
    title: toNullableString(source.name ?? source.title ?? input.listVideo.name ?? input.listVideo.title),
    description: toNullableString(source.description ?? input.listVideo.description),
    tagsJson: toTagsJson(source.tags ?? input.listVideo.tags),
    categoryId: category.id,
    category: category.label,
    licenceId: licence.id,
    licence: licence.label,
    language: language.id,
    languageLabel: language.label,
    nsfw: toNullableBoolean(source.nsfw ?? source.sensitive ?? input.listVideo.nsfw),
    sensitiveSummary: toNullableString(
      source.nsfwSummary ?? source.nsfw_summary ?? source.summary
    ),
    publishedAt: toNullableTimestamp(
      source.publishedAt ??
        source.published_at ??
        source.createdAt ??
        source.created_at ??
        input.listVideo.publishedAt ??
        input.listVideo.published_at
    ),
    originallyPublishedAt: toNullableTimestamp(
      source.originallyPublishedAt ?? source.originally_published_at
    ),
    updatedAt: toNullableTimestamp(source.updatedAt ?? source.updated_at),
    isLive,
    permanentLive,
    liveSaveReplay,
    aspectRatio: toNullableNumber(source.aspectRatio ?? source.aspect_ratio),
    support: toNullableString(source.support),
    accountUsername: account.username,
    accountName: account.displayName ?? account.username,
    accountUrl: account.url,
    accountAvatarUrl: account.avatarUrl,
    metadataVersion
  };
}

/** Return account/ownerAccount from a PeerTube channel object when present. */
function accountFromChannel(value: unknown): unknown {
  if (!value || typeof value !== "object") return null;
  const channel = value as Record<string, unknown>;
  return channel.account ?? channel.ownerAccount ?? null;
}

/** Normalize object/string/number identifier shapes used by PeerTube APIs. */
function extractIdentifierAndLabel(value: unknown): IdentifierLabel {
  if (typeof value === "string" || typeof value === "number") {
    return { id: toStringId(value), label: null };
  }
  if (!value || typeof value !== "object") {
    return { id: null, label: null };
  }
  return {
    id: extractIdentifier(value),
    label: extractDisplayLabel(value)
  };
}

/** Pick a deterministic avatar candidate from PeerTube array fields. */
function firstMediaCandidate(value: unknown): unknown {
  return Array.isArray(value) && value.length > 0 ? value[0] : null;
}

/** Encode only string tags, preserving current JSON storage semantics. */
function toTagsJson(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  return JSON.stringify(value.filter((item) => typeof item === "string"));
}

/** Normalize finite numeric values and numeric strings. */
function toNullableNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** Normalize booleans while keeping unavailable values distinct from false. */
function toNullableBoolean(value: unknown): number | null {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (value === 1 || value === "1" || value === "true") return 1;
  if (value === 0 || value === "0" || value === "false") return 0;
  return null;
}

/** Normalize source timestamps to the project's epoch-millisecond convention. */
function toNullableTimestamp(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/** Normalize identifiers that may be numeric or textual. */
function toStringId(value: unknown): string | null {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string") return nonBlank(value);
  return null;
}

/** Collapse blank strings to null to retain nullable storage semantics. */
function toNullableString(value: unknown): string | null {
  return typeof value === "string" ? nonBlank(value) : null;
}

/** Return a trimmed non-empty string. */
function nonBlank(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
