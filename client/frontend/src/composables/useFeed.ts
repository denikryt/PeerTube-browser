/** Stateful Home feed loader used by the Vue Home route. */
import { computed, reactive } from "vue";
import { fetchSimilarVideosPayload } from "../data/videos";
import type { VideoRow } from "../types/videos";

export type FeedMode = "recommendations" | "random";

/** Create feed state and actions around Client Discovery API v1 payloads. */
export function useFeed() {
  const state = reactive({
    mode: "recommendations" as FeedMode,
    rows: [] as VideoRow[],
    loading: false,
    error: "",
    nextCursor: null as string | null,
    generatedAt: null as number | null
  });

  const isEmpty = computed(() => !state.loading && !state.error && state.rows.length === 0);

  async function load(mode: FeedMode = state.mode, cursor?: string | null) {
    state.loading = true;
    state.error = "";
    state.mode = mode;
    try {
      const payload = await fetchSimilarVideosPayload({
        random: mode === "random" ? "1" : null,
        cursor: cursor ?? null
      });
      const rows = payload.rows ?? payload.items ?? [];
      if (cursor) {
        appendDeduped(rows);
      } else {
        state.rows = rows;
      }
      state.generatedAt = payload.generatedAt ?? null;
      state.nextCursor = payload.pagination?.next_cursor ?? null;
    } catch (error) {
      state.error = error instanceof Error ? error.message : "Failed to load feed";
    } finally {
      state.loading = false;
    }
  }

  function appendDeduped(rows: VideoRow[]) {
    const seen = new Set(state.rows.map((row) => `${row.instance_domain ?? row.instanceDomain ?? ""}::${row.video_uuid ?? row.videoUuid ?? row.video_id ?? ""}`));
    for (const row of rows) {
      const key = `${row.instance_domain ?? row.instanceDomain ?? ""}::${row.video_uuid ?? row.videoUuid ?? row.video_id ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      state.rows.push(row);
    }
  }

  return { state, isEmpty, load };
}
