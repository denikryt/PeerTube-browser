/**
 * Shared small status renderers for current string-based page updates.
 */

import { escapeHtml } from "../utils/format";

/** Render the current loading block markup. */
export function renderLoading(message = "Loading...") {
  return `<div class="loading">${escapeHtml(message)}</div>`;
}

/** Render the current error block markup. */
export function renderError(message: string) {
  return `<div class="error">${escapeHtml(message)}</div>`;
}
