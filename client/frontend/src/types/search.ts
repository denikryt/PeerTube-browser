/**
 * Search API v1 frontend payload types.
 */

import type { ChannelRow } from "./channels";
import type { DiscoveryPagination, VideoRow } from "./videos";

export interface SearchMeta {
  source: string;
  query: string;
  index?: string;
  filters?: {
    language: string | null;
    category: string | null;
    tag: string | null;
    instance: string | null;
  };
}

export interface VideoSearchPayload {
  items: VideoRow[];
  pagination: DiscoveryPagination;
  meta: SearchMeta;
}

export interface ChannelSearchPayload {
  items: ChannelRow[];
  pagination: DiscoveryPagination;
  meta: SearchMeta;
}
