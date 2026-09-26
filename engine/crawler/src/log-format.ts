/** Shared formatting for compact crawler progress messages. */

export type LogMetric = readonly [name: string, value: string | number | boolean];

/**
 * Format a crawler message with sortable counters immediately after its scope.
 *
 * Keeping metrics first makes interleaved multi-host output scannable while
 * preserving the event and subject at the end of every line.
 */
export function formatMetricLog(
  scope: string,
  metrics: readonly LogMetric[],
  event: string,
  subject?: string
) {
  const metricText = metrics.map(([name, value]) => `${name}=${value}`).join(" ");
  // Empty event/subject segments are intentionally omitted so result lines can
  // end directly with their host/channel identifier after the counters.
  return [`[${scope}]`, metricText, event, subject].filter(Boolean).join(" ");
}

/**
 * Create a crawl-wide ordinal allocator shared by all concurrent host workers.
 *
 * JavaScript assigns each number synchronously before a channel awaits network
 * I/O, so concurrent hosts cannot receive the same ordinal.
 */
export function createProgressOrdinal(total: number) {
  let current = 0;
  const safeTotal = Math.max(0, total);

  return () => {
    current += 1;
    return `${current}/${safeTotal}`;
  };
}
