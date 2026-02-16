export interface VideoRow {
  video_id?: string;
  video_uuid?: string | null;
  video_numeric_id?: number | null;
  instance_domain?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  channel_url?: string | null;
  channel_display_name?: string | null;
  account_name?: string | null;
  account_url?: string | null;
  title?: string | null;
  video_url?: string | null;
  duration?: number | null;
  thumbnail_url?: string | null;
  preview_path?: string | null;
  views?: number | null;
  likes?: number | null;
  dislikes?: number | null;
  comments_count?: number | null;
  embed_path?: string | null;
  description?: string | null;
  videoUrl?: string | null;
  videoUuid?: string | null;
  instanceDomain?: string | null;
  channelId?: string | null;
  channelName?: string | null;
  channelUrl?: string | null;
  channelDisplayName?: string | null;
  accountName?: string | null;
  accountUrl?: string | null;
  thumbnailUrl?: string | null;
  previewPath?: string | null;
  viewsCount?: number | null;
  likes_count?: number | null;
  dislikes_count?: number | null;
  commentsCount?: number | null;
  embedPath?: string | null;
  published_at?: number | null;
  publishedAt?: number | null;
  channel_avatar_url?: string | null;
  account_avatar_url?: string | null;
  avatar_url?: string | null;
  channelAvatarUrl?: string | null;
  accountAvatarUrl?: string | null;
  avatarUrl?: string | null;
  debug?: {
    score?: number | null;
    similarity_score?: number | null;
    freshness_score?: number | null;
    popularity_score?: number | null;
    layer?: string | null;
    rank_before?: number | null;
    rank_after?: number | null;
  } | null;
}

export interface SimilarSeed {
  title?: string | null;
  video_id?: string | null;
  instance_domain?: string | null;
}

export interface VideosPayload {
  generatedAt?: number;
  total?: number;
  rows?: VideoRow[];
  seed?: SimilarSeed | null;
}
