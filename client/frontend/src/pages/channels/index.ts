/**
 * Module `client/frontend/src/pages/channels/index.ts`: provide runtime functionality.
 */

import "../../channels.css";
import { fetchChannelsPayload } from "../../data/channels";
import type { ChannelRow } from "../../types/channels";

const body = document.getElementById("channels-body");
const summaryCounts = document.getElementById("summary-counts");
const summaryMeta = document.getElementById("summary-meta");
const pageStatus = document.getElementById("page-status");
const pagePrev = document.getElementById("page-prev");
const pageNext = document.getElementById("page-next");
const pageSizeSelect = document.getElementById("page-size") as HTMLSelectElement | null;
const searchInput = document.getElementById("filter-search") as HTMLInputElement | null;
const instanceInput = document.getElementById("filter-instance") as HTMLInputElement | null;
const followersInput = document.getElementById("filter-followers") as HTMLInputElement | null;
const videosInput = document.getElementById("filter-videos") as HTMLInputElement | null;
const videosMaxInput = document.getElementById("filter-videos-max") as HTMLInputElement | null;
const clearButton = document.getElementById("clear-filters");
const sortButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("button[data-sort]"));

if (!body || !summaryCounts || !summaryMeta || !pageStatus) {
  throw new Error("Missing channels table elements");
}

type SortKey = "name" | "instance" | "videos" | "followers" | "checked";
type SortDir = "asc" | "desc";

const numberFormat = new Intl.NumberFormat("en-US");
const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });
const params = new URLSearchParams(window.location.search);
const apiParam = params.get("api");
const FILTER_DEBOUNCE_MS = 250;

const state = {
  rows: [] as ChannelRow[],
  total: 0,
  sortKey: "followers" as SortKey,
  sortDir: "desc" as SortDir,
  generatedAt: null as number | null,
  page: 1,
  pageSize: 100,
  loading: false,
  requestSeq: 0
};

const filterState = {
  search: "",
  instance: "",
  minFollowers: 0,
  minVideos: 0,
  maxVideos: null as number | null
};

let filterDebounceTimer = 0;

wireFilters();
wireSorters();
updateSortIndicators();
void loadChannels();

/**
 * Handle wire filters.
 */
function wireFilters() {
  /**
   * Handle on change.
   */
  const onChange = () => {
    filterState.search = (searchInput?.value ?? "").trim();
    filterState.instance = (instanceInput?.value ?? "").trim();
    filterState.minFollowers = Number(followersInput?.value ?? 0) || 0;
    filterState.minVideos = Number(videosInput?.value ?? 0) || 0;
    const rawMaxVideos = (videosMaxInput?.value ?? "").trim();
    if (!rawMaxVideos) {
      filterState.maxVideos = null;
    } else {
      const maxVideosValue = Number(rawMaxVideos);
      filterState.maxVideos = Number.isFinite(maxVideosValue) && maxVideosValue >= 0 ? maxVideosValue : null;
    }
    state.page = 1;
    scheduleLoad();
  };

  searchInput?.addEventListener("input", onChange);
  instanceInput?.addEventListener("input", onChange);
  followersInput?.addEventListener("input", onChange);
  videosInput?.addEventListener("input", onChange);
  videosMaxInput?.addEventListener("input", onChange);

  clearButton?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    if (instanceInput) instanceInput.value = "";
    if (followersInput) followersInput.value = "";
    if (videosInput) videosInput.value = "";
    if (videosMaxInput) videosMaxInput.value = "";
    onChange();
  });

  pagePrev?.addEventListener("click", () => {
    if (state.loading || state.page <= 1) return;
    state.page -= 1;
    void loadChannels();
  });

  pageNext?.addEventListener("click", () => {
    if (state.loading) return;
    const maxPage = maxPageCount();
    if (state.page >= maxPage) return;
    state.page += 1;
    void loadChannels();
  });

  pageSizeSelect?.addEventListener("change", () => {
    const value = Number(pageSizeSelect.value);
    state.pageSize = Number.isFinite(value) && value > 0 ? value : 100;
    state.page = 1;
    void loadChannels();
  });
}

/**
 * Handle wire sorters.
 */
function wireSorters() {
  sortButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const key = (button.dataset.sort ?? "followers") as SortKey;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = defaultSortDir(key);
      }
      state.page = 1;
      updateSortIndicators();
      void loadChannels();
    });
  });
}

/**
 * Handle schedule load.
 */
function scheduleLoad() {
  window.clearTimeout(filterDebounceTimer);
  filterDebounceTimer = window.setTimeout(() => {
    void loadChannels();
  }, FILTER_DEBOUNCE_MS);
}

/**
 * Handle max page count.
 */
function maxPageCount() {
  return Math.max(1, Math.ceil(state.total / state.pageSize));
}

/**
 * Handle load channels.
 */
async function loadChannels() {
  const requestSeq = ++state.requestSeq;
  state.loading = true;
  renderSummary();
  renderLoadingRow();

  try {
    const payload = await fetchChannelsPayload({
      apiBase: apiParam,
      limit: state.pageSize,
      offset: (state.page - 1) * state.pageSize,
      q: filterState.search,
      instance: filterState.instance,
      minFollowers: filterState.minFollowers,
      minVideos: filterState.minVideos,
      maxVideos: filterState.maxVideos,
      sort: state.sortKey,
      dir: state.sortDir
    });
    if (requestSeq !== state.requestSeq) return;

    const rows = Array.isArray(payload) ? payload : payload.rows ?? [];
    const total = Array.isArray(payload) ? rows.length : payload.total ?? rows.length;
    const maxPage = Math.max(1, Math.ceil(total / state.pageSize));
    if (state.page > maxPage) {
      state.page = maxPage;
      void loadChannels();
      return;
    }

    state.rows = rows;
    state.total = total;
    state.generatedAt = Array.isArray(payload) ? null : payload.generatedAt ?? null;
    renderTable();
    renderSummary();
  } catch (error) {
    if (requestSeq !== state.requestSeq) return;
    const message = error instanceof Error ? error.message : "Load error";
    state.rows = [];
    state.total = 0;
    summaryCounts.textContent = message;
    summaryMeta.textContent = "";
    body.innerHTML = `<tr><td class="empty" colspan="6">${escapeHtml(message)}</td></tr>`;
  } finally {
    if (requestSeq !== state.requestSeq) return;
    state.loading = false;
    renderSummary();
  }
}

/**
 * Handle render summary.
 */
function renderSummary() {
  const total = state.total;
  const maxPage = maxPageCount();
  const from = total > 0 ? (state.page - 1) * state.pageSize + 1 : 0;
  const to = total > 0 ? Math.min(total, from + state.rows.length - 1) : 0;

  if (state.loading) {
    summaryCounts.textContent = "Loading...";
  } else if (total === 0) {
    summaryCounts.textContent = "No channels found";
  } else {
    summaryCounts.textContent = `Showing ${numberFormat.format(from)}-${numberFormat.format(to)} of ${numberFormat.format(total)} channels`;
  }

  if (state.generatedAt) {
    const date = new Date(state.generatedAt);
    summaryMeta.textContent = `Updated ${dateFormat.format(date)}`;
  } else {
    summaryMeta.textContent = "";
  }

  pageStatus.textContent = `${state.page} / ${maxPage}`;
  if (pagePrev) pagePrev.toggleAttribute("disabled", state.loading || state.page <= 1);
  if (pageNext) pageNext.toggleAttribute("disabled", state.loading || state.page >= maxPage);
}

/**
 * Handle render loading row.
 */
function renderLoadingRow() {
  body.innerHTML = `<tr><td class="empty" colspan="6">Loading...</td></tr>`;
}

/**
 * Handle render table.
 */
function renderTable() {
  if (state.rows.length === 0) {
    body.innerHTML = `<tr><td class="empty" colspan="6">No results found.</td></tr>`;
    return;
  }

  body.innerHTML = state.rows
    .map((row) => {
      const url = channelUrl(row);
      const label = channelLabel(row);
      const followers = row.followers_count ?? 0;
      const videos = row.videos_count ?? 0;
      const checked = row.health_checked_at ? dateFormat.format(new Date(row.health_checked_at)) : "—";
      const errorTag = row.last_error
        ? `<span class="pill">${row.last_error_source === "videos_count" ? "count error" : "error"}</span>`
        : "";
      const avatar = row.avatar_url
        ? `<img class="avatar" src="${escapeHtml(row.avatar_url)}" alt="" loading="lazy" />`
        : `<div class="avatar-fallback">—</div>`;
      return `
        <tr>
          <td class="avatar-cell">${avatar}</td>
          <td>
            <div class="channel-cell">
              <a class="channel-name" href="${url}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>
              <div class="channel-meta">${escapeHtml(row.instance_domain ?? "")} ${errorTag}</div>
            </div>
          </td>
          <td>${escapeHtml(row.instance_domain ?? "—")}</td>
          <td class="num">${numberFormat.format(videos)}</td>
          <td class="num">${numberFormat.format(followers)}</td>
          <td class="num">${checked}</td>
        </tr>
      `;
    })
    .join("");
}

/**
 * Handle default sort dir.
 */
function defaultSortDir(key: SortKey): SortDir {
  if (key === "name" || key === "instance") return "asc";
  return "desc";
}

/**
 * Handle update sort indicators.
 */
function updateSortIndicators() {
  sortButtons.forEach((button) => {
    const key = button.dataset.sort;
    if (key === state.sortKey) {
      button.dataset.dir = state.sortDir;
    } else {
      button.dataset.dir = "";
    }
  });
}

/**
 * Handle channel label.
 */
function channelLabel(row: ChannelRow) {
  return row.display_name ?? row.channel_name ?? row.channel_id ?? "unknown";
}

/**
 * Handle channel url.
 */
function channelUrl(row: ChannelRow) {
  if (row.channel_url) return row.channel_url;
  if (row.channel_name && row.instance_domain) {
    return `https://${row.instance_domain}/video-channels/${encodeURIComponent(row.channel_name)}`;
  }
  return "#";
}

/**
 * Handle escape html.
 */
function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "\"":
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return char;
    }
  });
}
