/** Share one fatal signal between sibling hosts and nested crawler stages. */

/** Owned by one CLI invocation (or host pipeline), never by a module singleton. */
export interface WorkCancellation {
  stopped: boolean;
  reason?: unknown;
}

/** First fatal error wins; publish before waiting for sibling I/O to drain. */
export function stopWork(cancellation: WorkCancellation, reason: unknown): void {
  if (!cancellation.stopped) {
    cancellation.stopped = true;
    cancellation.reason = reason;
  }
}

/** Called before dequeuing new identities and at the request-limiter I/O boundary. */
export function assertWorkActive(cancellation: WorkCancellation): void {
  if (cancellation.stopped) throw cancellation.reason ?? new Error("Crawler work cancelled");
}
