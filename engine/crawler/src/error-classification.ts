/** Classify crawler failures for human-readable persistence in existing error columns. */

/** Return the message carried by an unknown thrown value. */
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Return a transport code from an error or its immediate cause. */
function errorCode(error: unknown): string {
  if (!error || typeof error !== "object") return "";
  const value = error as { code?: unknown; cause?: { code?: unknown } };
  const code = value.cause?.code ?? value.code;
  return typeof code === "string" ? code.toUpperCase() : "";
}

export interface CrawlErrorClassification {
  kind: string;
  retryable: boolean;
  tryAlternateProtocol: boolean;
}

/** Classify one failure for persistence, retries, and protocol fallback. */
export function classifyCrawlError(error: unknown): CrawlErrorClassification {
  const message = errorMessage(error);
  const lower = message.toLowerCase();
  const name = error instanceof Error ? error.name : "";
  const code = errorCode(error);
  const http = message.match(/HTTP\s+(\d{3})/i);

  if (name === "AbortError" || lower.includes("timeout") || code.includes("TIMEOUT")) {
    return { kind: "timeout", retryable: true, tryAlternateProtocol: true };
  }
  if (http) {
    const status = Number(http[1]);
    const retryable = status === 408 || status === 425 || status === 429 || status >= 500;
    return { kind: `http_${status}`, retryable, tryAlternateProtocol: false };
  }
  if (code === "ERR_SSL_WRONG_VERSION_NUMBER") {
    return { kind: "tls", retryable: false, tryAlternateProtocol: true };
  }
  if (code.includes("CERT") || code.includes("TLS") || lower.includes("certificate")) {
    return { kind: "tls", retryable: false, tryAlternateProtocol: false };
  }
  if (error instanceof SyntaxError || lower.includes("invalid json")) {
    return { kind: "invalid_json", retryable: false, tryAlternateProtocol: false };
  }
  const transientNetworkCodes = ["EAI_AGAIN", "ECONNRESET", "EPIPE"];
  const terminalNetworkCodes = ["ENETUNREACH", "EHOSTUNREACH", "ENOTFOUND", "ECONNREFUSED"];
  if (transientNetworkCodes.includes(code)) {
    return { kind: "network", retryable: true, tryAlternateProtocol: true };
  }
  if (terminalNetworkCodes.includes(code)) {
    return { kind: "network", retryable: false, tryAlternateProtocol: false };
  }
  return { kind: "unknown", retryable: false, tryAlternateProtocol: false };
}

/** Return whether an HTTPS/HTTP alternate can plausibly change the outcome. */
export function shouldTryAlternateProtocol(error: unknown): boolean {
  return classifyCrawlError(error).tryAlternateProtocol;
}

/**
 * Format an error with a stable category while retaining its original detail.
 *
 * The prefix deliberately lives in the existing `last_error` text field, so
 * operators gain queryable failure kinds without another SQLite migration.
 */
export function formatCrawlError(error: unknown): string {
  const message = errorMessage(error);
  const { kind } = classifyCrawlError(error);

  return `[${kind}] ${message}`;
}
