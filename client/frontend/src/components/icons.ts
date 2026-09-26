/**
 * Shared SVG icon snippets used by vanilla string renderers.
 */

/** Current eye icon markup used by stat displays. */
export function iconEye() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="3.2" />
    </svg>
  `;
}

/** Current thumbs-up icon markup used by feed/video actions. */
export function iconThumbUp() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

/** Current thumbs-down icon markup used by feed/video actions. */
export function iconThumbDown() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `;
}
