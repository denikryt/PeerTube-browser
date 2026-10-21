/** Bound concurrent network operations that target one remote host. */

export interface RequestLimiter {
  /** Run one operation after a per-host concurrency slot becomes available. */
  run<T>(operation: () => Promise<T>): Promise<T>;
}

/**
 * Create a FIFO semaphore for requests sent to one PeerTube instance.
 *
 * Holding the slot across retries and backoff prevents nested channel/detail
 * pools from multiplying the operator's requested per-host pressure. Reserving
 * request start times centrally makes the host delay apply to every crawl mode,
 * including concurrent channel pages and per-video detail enrichment.
 * A caller-owned guard runs after any queued wait or host delay, immediately
 * before actual I/O. This prevents an already queued identity from starting
 * after an unrelated host reports a fatal run-wide error. An optional operation
 * error hook runs before releasing a slot, so queued requests cannot overtake
 * publication of an explicit local outage.
 */
export function createRequestLimiter(
  concurrency: number,
  delayMs = 0,
  assertBeforeStart?: () => void,
  onOperationError?: (error: unknown) => void,
): RequestLimiter {
  const limit = Math.max(1, Math.floor(concurrency));
  const minimumDelayMs = Math.max(0, Math.floor(delayMs));
  let active = 0;
  let nextStartAt = 0;
  const waiting: Array<() => void> = [];

  const acquire = async () => {
    if (active < limit) {
      active += 1;
      return;
    }
    await new Promise<void>((resolve) => waiting.push(resolve));
  };

  const release = () => {
    const next = waiting.shift();
    if (next) {
      // Transfer the occupied slot directly to the oldest waiter. Keeping the
      // active count unchanged avoids a microtask gap where a newcomer could
      // bypass the queued operation and temporarily exceed the limit.
      next();
      return;
    }
    active -= 1;
  };

  return {
    async run<T>(operation: () => Promise<T>): Promise<T> {
      await acquire();
      try {
        // Timers can become overdue together while the event loop is blocked.
        // Recheck the last actual start after every wakeup so missed slots never
        // become a catch-up burst. The monotonic clock ignores wall-clock jumps.
        while (nextStartAt > performance.now()) {
          await new Promise<void>((resolve) =>
            setTimeout(resolve, Math.max(1, nextStartAt - performance.now())));
        }
        assertBeforeStart?.();
        // No await separates admission from the operation, so sibling holders
        // observe this start before they can enter their own operation.
        nextStartAt = performance.now() + minimumDelayMs;
        try {
          return await operation();
        } catch (error) {
          // Publish a fatal signal before releasing the occupied FIFO slot.
          // Otherwise a waiting request could start before its owner catches it.
          onOperationError?.(error);
          throw error;
        }
      } finally {
        release();
      }
    }
  };
}
