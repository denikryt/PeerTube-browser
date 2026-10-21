/**
 * Frontend project API facade. It exposes Client-backend calls without direct Engine access.
 */

export { resolveClientApiBase } from "../data/api-base";
export { fetchChannelsPayload } from "../data/channels";
export { addLocalLike, clearLocalLikes, getRandomLikes, getStoredLikes } from "../data/local-likes";
export { sendUserAction } from "../data/user-actions";
export { fetchUserProfileLikes, resetUserProfileLikes } from "../data/user-profile";
export { fetchSimilarVideosPayload, fetchStaticVideosPayload, parseSimilarQuery, resolveApiBase, buildSimilarUrl } from "../data/videos";
export { fetchVideoSearchPayload, fetchChannelSearchPayload, buildVideoSearchUrl, buildChannelSearchUrl } from "../data/search";
export type { SimilarQuery } from "../data/videos";
