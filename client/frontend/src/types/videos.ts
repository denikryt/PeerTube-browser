/**
 * Module `client/frontend/src/types/videos.ts`: provide runtime functionality.
 */

/** Browser-safe thumbnail source plus optional PeerTube pixel dimensions. */
export interface ThumbnailCandidate {
  url: string;
  width: number | null;
  height: number | null;
}

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
  /** Canonical browser-ready card image URL after Client API normalization. */
  thumbnail_url?: string | null;
  /** Ordered browser-ready thumbnail candidates from the Client API. */
  thumbnail_urls?: string[] | null;
  /** Ordered browser-ready thumbnail objects used for responsive source choice. */
  thumbnail_candidates?: ThumbnailCandidate[] | null;
  /** Source/legacy PeerTube preview field; not used directly by feed cards. */
  preview_path?: string | null;
  views?: number | null;
  likes?: number | null;
  dislikes?: number | null;
  comments_count?: number | null;
  language?: string | null;
  language_label?: string | null;
  category?: string | null;
  category_id?: string | null;
  tags_json?: string | null;
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
  thumbnailUrls?: string[] | null;
  thumbnailCandidates?: ThumbnailCandidate[] | null;
  previewPath?: string | null;
  viewsCount?: number | null;
  likes_count?: number | null;
  dislikes_count?: number | null;
  commentsCount?: number | null;
  languageLabel?: string | null;
  categoryId?: string | null;
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


export interface DiscoveryPagination {
  limit: number;
  next_cursor: string | null;
  has_more: boolean;
}

export interface DiscoveryMeta {
  source: string;
  fallback?: boolean;
  fallback_reason?: string | null;
  filters?: {
    language: string | null;
    category: string | null;
    tag: string | null;
    instance: string | null;
  };
}

export interface DiscoveryListPayload {
  items: VideoRow[];
  pagination: DiscoveryPagination;
  meta: DiscoveryMeta;
  generatedAt?: number;
  total?: number;
  rows?: VideoRow[];
  seed?: SimilarSeed | null;
}

export interface VideosPayload {
  generatedAt?: number;
  total?: number;
  rows?: VideoRow[];
  seed?: SimilarSeed | null;
  pagination?: DiscoveryPagination;
  meta?: DiscoveryMeta;
  items?: VideoRow[];
}
