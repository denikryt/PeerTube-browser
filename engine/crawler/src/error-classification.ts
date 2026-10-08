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
  httpStatus: number | null;
}

/** Read a validated HTTP status carried structurally by a thrown value. */
function structuralHttpStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("status" in error)) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" && Number.isInteger(status) && status >= 100 && status <= 599
    ? status
    : null;
}

/** Parse the legacy defensive HTTP status fallback from human-readable text. */
function messageHttpStatus(message: string): number | null {
  const match = message.match(/HTTP\s+(\d{3})/i);
  if (!match) return null;
  const status = Number(match[1]);
  return status >= 100 && status <= 599 ? status : null;
}

/** Classify one failure for persistence, retries, and protocol fallback. */
export function classifyCrawlError(error: unknown): CrawlErrorClassification {
  const message = errorMessage(error);
  const lower = message.toLowerCase();
  const name = error instanceof Error ? error.name : "";
  const code = errorCode(error);
  const structuralStatus = structuralHttpStatus(error);

  // Response.status is stronger evidence than names or human-readable text.
  // HTTP responses must never gain alternate-protocol authority merely because
  // an attached diagnostic happens to contain a transport keyword.
  if (structuralStatus !== null) {
    const retryable =
      structuralStatus === 408 ||
      structuralStatus === 425 ||
      structuralStatus === 429 ||
      structuralStatus >= 500;
    return {
      kind: `http_${structuralStatus}`,
      retryable,
      tryAlternateProtocol: false,
      httpStatus: structuralStatus
    };
  }

  if (name === "AbortError" || lower.includes("timeout") || code.includes("TIMEOUT")) {
    return { kind: "timeout", retryable: true, tryAlternateProtocol: true, httpStatus: null };
  }

  // Decoder failures are typed evidence that no HTTP status was observed from
  // the response itself. Their diagnostics may contain remote body text, so
  // message-based compatibility parsing must never reinterpret them as 404/410.
  if (error instanceof SyntaxError || lower.includes("invalid json")) {
    return { kind: "invalid_json", retryable: false, tryAlternateProtocol: false, httpStatus: null };
  }

  const fallbackStatus = messageHttpStatus(message);
  if (fallbackStatus !== null) {
    const retryable =
      fallbackStatus === 408 || fallbackStatus === 425 || fallbackStatus === 429 || fallbackStatus >= 500;
    return {
      kind: `http_${fallbackStatus}`,
      retryable,
      tryAlternateProtocol: false,
      httpStatus: fallbackStatus
    };
  }
  if (code === "ERR_SSL_WRONG_VERSION_NUMBER") {
    return { kind: "tls", retryable: false, tryAlternateProtocol: true, httpStatus: null };
  }
  if (code.includes("CERT") || code.includes("TLS") || lower.includes("certificate")) {
    return { kind: "tls", retryable: false, tryAlternateProtocol: false, httpStatus: null };
  }
  const transientNetworkCodes = ["EAI_AGAIN", "ECONNRESET", "EPIPE"];
  const terminalNetworkCodes = ["ENETUNREACH", "EHOSTUNREACH", "ENOTFOUND", "ECONNREFUSED"];
  if (transientNetworkCodes.includes(code)) {
    return { kind: "network", retryable: true, tryAlternateProtocol: true, httpStatus: null };
  }
  if (terminalNetworkCodes.includes(code)) {
    return { kind: "network", retryable: false, tryAlternateProtocol: false, httpStatus: null };
  }
  return { kind: "unknown", retryable: false, tryAlternateProtocol: false, httpStatus: null };
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
