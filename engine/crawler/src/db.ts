/**
 * Compatibility facade for crawler database stores.
 *
 * Stage 7 splits the monolithic implementation into narrow modules, but this
 * file keeps the historical public import path used by workers and local scripts.
 */

export { CrawlerStore } from "./db/instances.js";
export { ChannelStore } from "./db/channels.js";
export { VideoStore } from "./db/videos.js";
export type {
  ChannelCounts,
  ChannelCrawlStatus,
  ChannelProgressRow,
  ChannelRow,
  ChannelStoreOptions,
  ChannelUpsertRow,
  StoreOptions,
  VideoChannelRow,
  VideoCrawlStatus,
  VideoProgressRow,
  VideoStoreOptions,
  VideoTagRow,
  VideoUpsertRow
} from "./db/types.js";
