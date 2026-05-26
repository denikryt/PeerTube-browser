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
  publishedAt: number | null;
  videoUrl: string | null;
  duration: number | null;
  thumbnailUrl: string | null;
  embedPath: string | null;
  views: number | null;
  likes: number | null;
  dislikes: number | null;
  commentsCount: number | null;
  nsfw: number | null;
  previewPath: string | null;
  lastCheckedAt: number;
}
