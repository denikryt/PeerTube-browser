/**
 * Type definitions for crawler database stores.
 *
 * These types describe the current row and option contracts exported by
 * engine/crawler/src/db.ts. They do not introduce new crawler behavior.
 */

export interface StoreOptions {
  dbPath: string;
  resume: boolean;
  collectGraph: boolean;
  expandBeyondWhitelist: boolean;
}

export interface ChannelStoreOptions {
  dbPath: string;
}

export interface VideoStoreOptions {
  dbPath: string;
  /** Metadata maintenance can opt out after an explicit current-schema check. */
  initializeSchema?: boolean;
}

export type ChannelCrawlStatus = "pending" | "in_progress" | "done" | "error";

export interface ChannelUpsertRow {
  channelId: string;
  channelName: string | null;
  channelUrl: string | null;
  displayName: string | null;
  instanceDomain: string;
  videosCount: number | null;
  followersCount: number | null;
  avatarUrl: string | null;
  ownerAccountUsername?: string | null;
  ownerAccountDisplayName?: string | null;
  ownerAccountUrl?: string | null;
  ownerAccountAvatarUrl?: string | null;
}

export interface ChannelRow {
  channel_id: string;
  channel_name: string | null;
  instance_domain: string;
  videos_count: number | null;
  health_status: string | null;
  health_checked_at: number | null;
  health_error: string | null;
  last_error: string | null;
  last_error_at: number | null;
  last_error_source: string | null;
}

export interface ChannelCounts {
  total: number;
  withVideos: number;
  withError: number;
}

export interface ChannelProgressRow {
  instanceDomain: string;
  status: ChannelCrawlStatus;
  lastStart: number;
}

export type VideoCrawlStatus = "pending" | "in_progress" | "done" | "error";

export interface VideoChannelRow {
  channel_id: string;
  channel_name: string | null;
  display_name: string | null;
  channel_url: string | null;
  instance_domain: string;
  videos_count: number | null;
}

export interface VideoProgressRow {
  instanceDomain: string;
  channelId: string;
  channelName: string | null;
  status: VideoCrawlStatus;
  lastStart: number;
  lastError: string | null;
}

export interface VideoTagRow {
  videoId: string;
  videoUuid: string;
  instanceDomain: string;
}

export interface VideoThumbnailRow {
  videoId: string;
  videoUuid: string;
  instanceDomain: string;
}

export interface VideoUpsertRow {
  videoId: string;
  videoUuid: string | null;
  videoNumericId: number | null;
  instanceDomain: string;
  channelId: string | null;
  channelName: string | null;
  channelUrl: string | null;
  accountName: string | null;
  accountUrl: string | null;
  title: string | null;
  description: string | null;
  tagsJson: string | null;
  category: string | null;
  categoryId?: string | null;
  licenceId?: string | null;
  licence?: string | null;
  language?: string | null;
  languageLabel?: string | null;
  publishedAt: number | null;
  originallyPublishedAt?: number | null;
  updatedAt?: number | null;
  videoUrl: string | null;
  duration: number | null;
  thumbnailUrl: string | null;
  thumbnailWidth?: number | null;
  thumbnailHeight?: number | null;
  embedPath: string | null;
  views: number | null;
  likes: number | null;
  dislikes: number | null;
  commentsCount: number | null;
  nsfw: number | null;
  sensitiveSummary?: string | null;
  isLive?: number | null;
  permanentLive?: number | null;
  liveSaveReplay?: number | null;
  aspectRatio?: number | null;
  support?: string | null;
  accountUsername?: string | null;
  accountAvatarUrl?: string | null;
  metadataVersion?: number;
  previewPath: string | null;
  lastCheckedAt: number;
}

/**
 * Metadata that may be applied only after a successful per-video detail read.
 * Optional live keys distinguish an absent remote field from an explicit false.
 */
export interface VideoDetailMetadataPatch {
  categoryId: string | null;
  category: string | null;
  licenceId: string | null;
  licence: string | null;
  language: string | null;
  languageLabel: string | null;
  sensitiveSummary: string | null;
  originallyPublishedAt: number | null;
  updatedAt: number | null;
  aspectRatio: number | null;
  support: string | null;
  accountUsername: string | null;
  accountAvatarUrl: string | null;
  permanentLive?: number | null;
  liveSaveReplay?: number | null;
}

/** Public ActivityPub live fields fetched independently from REST detail. */
export interface VideoActivityPubMetadataPatch {
  permanentLive?: number;
  liveSaveReplay?: number;
}

/**
 * Existing-row refresh separates always-refreshable base data from successful
 * enrichment sources so persistence never has to infer provenance from flags.
 */
export interface ExistingVideoRefresh {
  base: VideoUpsertRow;
  detail?: VideoDetailMetadataPatch;
  activityPub?: VideoActivityPubMetadataPatch;
}

export interface VideoMetadataWorkRow {
  videoId: string;
  videoUuid: string;
  instanceDomain: string;
  metadataVersion?: number;
  videoUrl: string | null;
}
