/**
 * Coordinate browser thumbnail request starts across cards sharing one origin.
 *
 * PeerTube instances are independent remote servers. Spacing starts prevents a
 * single slow instance from receiving a burst of card-image requests while
 * preserving immediate rendering for the first candidate of every host.
 */

const SAME_HOST_DELAY_MS = 500;
const nextStartByHost = new Map<string, number>();

/** Resolve a canonical request host, leaving malformed values unscheduled. */
function thumbnailHost(url: string): string | null {
  try {
    return new URL(url).host || null;
  } catch {
    return null;
  }
}

/** Release host state after its last reserved interval so long feeds do not retain origins. */
function scheduleHostCleanup(host: string, expectedNextStart: number, now: number) {
  globalThis.setTimeout(() => {
    if (nextStartByHost.get(host) === expectedNextStart && Date.now() >= expectedNextStart) {
      nextStartByHost.delete(host);
    }
  }, Math.max(0, expectedNextStart - now));
}

/** Reserve a request-start slot and return the required delay in milliseconds.

 * Reservation is synchronous so a first same-host image can retain its normal
 * immediate rendering path. Subsequent cards receive slots 500 ms apart even
 * when Vue mounts them in the same task.
 */
export function reserveThumbnailRequestStart(url: string): number {
  const host = thumbnailHost(url);
  if (!host) return 0;
  const now = Date.now();
  const startAt = Math.max(now, nextStartByHost.get(host) ?? now);
  const nextStart = startAt + SAME_HOST_DELAY_MS;
  nextStartByHost.set(host, nextStart);
  scheduleHostCleanup(host, nextStart, now);
  return startAt - now;
}

/** Reset module state between isolated component tests. */
export function resetThumbnailRequestScheduleForTests() {
  nextStartByHost.clear();
}
