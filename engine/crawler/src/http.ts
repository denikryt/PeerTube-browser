/**
 * Module `engine/crawler/src/http.ts`: provide runtime functionality.
 */

import { setTimeout as sleep } from "node:timers/promises";
import { setDefaultResultOrder } from "node:dns";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { classifyCrawlError } from "./error-classification.js";

// Prefer IPv4 first to avoid IPv6 timeouts on some instances.
setDefaultResultOrder("ipv4first");
const execFileAsync = promisify(execFile);

export interface HttpOptions {
  timeoutMs: number;
  maxRetries: number;
  log?: (message: string) => void;
  /** Optional response content type used by protocol-specific callers. */
  accept?: string;
  /** Fetch-compatible redirect policy; REST callers keep the default follow behavior. */
  redirect?: "follow" | "error";
}

/**
 * Represent no network error behavior.
 */
export class NoNetworkError extends Error {
  code = "NO_NETWORK";
  /**
   * Initialize the instance.
   */
  constructor(message: string) {
    super(message);
    this.name = "NoNetworkError";
  }
}

/**
 * Check whether is no network error.
 */
export function isNoNetworkError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  if (error instanceof NoNetworkError) return true;
  const err = error as { code?: string; cause?: { code?: string } };
  const code = err.cause?.code ?? err.code;
  if (typeof code !== "string" || code.length === 0) return false;
  const upper = code.toUpperCase();
  return (
    upper === "ENETUNREACH" ||
    upper === "EHOSTUNREACH" ||
    upper === "ENOTFOUND" ||
    upper === "EAI_AGAIN" ||
    upper === "ECONNREFUSED" ||
    upper === "ETIMEDOUT" ||
    upper === "ETIMEOUT"
  );
}

export async function fetchJsonWithRetry<T>(url: string, options: HttpOptions): Promise<T> {
  let attempt = 0;
  let backoff = 1000;

  while (true) {
    attempt += 1;
    const controller = new AbortController();
    let timedOut = false;
    const startedAt = Date.now();
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, options.timeoutMs);

    try {
      let response: Response;
      try {
        response = await fetch(url, {
          signal: controller.signal,
          redirect: options.redirect ?? "follow",
          headers: {
            "accept": options.accept ?? "application/json"
          }
        });
      } catch (error) {
        if (!isNoNetworkError(error)) {
          throw error;
        }
        response = await fetchViaCurl(url, options);
      }

      if (!response.ok) {
        const statusError = new Error(`HTTP ${response.status} for ${url}`) as Error & {
          retryAfterMs?: number | null;
        };
        statusError.retryAfterMs = parseRetryAfter(response.headers.get("retry-after"));
        throw statusError;
      }

      return (await response.json()) as T;
    } catch (error) {
      if (isNoNetworkError(error)) {
        const message = error instanceof Error ? error.message : String(error);
        throw new NoNetworkError(message);
      }
      const classification = classifyCrawlError(error);
      if (!classification.retryable || attempt > options.maxRetries) {
        throw error;
      }
      const elapsedMs = Date.now() - startedAt;
      const reason = extractErrorReason(error, {
        timedOut,
        timeoutMs: options.timeoutMs,
        elapsedMs
      });
      const debug = extractErrorDebug(error, {
        timedOut,
        timeoutMs: options.timeoutMs,
        elapsedMs
      });
      const debugSuffix = debug ? `\n${debug}` : "";
      const retryAfterMs =
        error && typeof error === "object" && "retryAfterMs" in error
          ? (error as { retryAfterMs?: number | null }).retryAfterMs
          : null;
      const delay = retryAfterMs ?? backoff;
      const logMessage = `---\n[http] retry kind=${classification.kind} attempt=${attempt}/${options.maxRetries} retry_in_ms=${delay}\n${url}\nreason=${reason}${debugSuffix}`;
      if (options.log) {
        options.log(logMessage);
      } else {
        console.warn(logMessage);
      }
      await sleep(delay);
      backoff = Math.min(backoff * 2, 30000);
    } finally {
      clearTimeout(timeout);
    }
  }
}

/**
 * Handle fetch via curl.
 */
async function fetchViaCurl(url: string, options: HttpOptions): Promise<Response> {
  try {
    const { stdout } = await execFileAsync("curl", buildCurlArgs(url, options));
    const marker = "\n__PEERTUBE_STATUS__=";
    const markerIndex = stdout.lastIndexOf(marker);
    if (markerIndex < 0) {
      throw new Error("curl response missing HTTP status marker");
    }
    const body = stdout.slice(0, markerIndex);
    const status = Number(stdout.slice(markerIndex + marker.length).trim());
    if (!Number.isInteger(status) || status < 100 || status > 599) {
      throw new Error("curl returned invalid HTTP status");
    }
    return new Response(body, { status });
  } catch (error) {
    const err = error as { stderr?: string; message?: string };
    const stderr = typeof err.stderr === "string" ? err.stderr.trim() : "";
    const message = stderr || err.message || "curl failed";
    throw new Error(`curl: ${message}`);
  }
}

/**
 * Build curl arguments with the same Accept and redirect semantics as native
 * fetch. Exporting this pure boundary keeps the fallback contract testable.
 */
export function buildCurlArgs(url: string, options: HttpOptions): string[] {
  const timeoutSec = Math.max(1, Math.ceil(options.timeoutMs / 1000));
  const args = [
    "--silent",
    "--show-error",
    "--max-time",
    String(timeoutSec),
    "--connect-timeout",
    String(timeoutSec),
    "--header",
    `accept: ${options.accept ?? "application/json"}`,
    "--write-out",
    "\n__PEERTUBE_STATUS__=%{http_code}"
  ];
  if (options.redirect !== "error") {
    args.push("--location");
  }
  args.push(url);
  return args;
}

interface ErrorContext {
  elapsedMs: number;
  timedOut: boolean;
  timeoutMs: number;
}

/**
 * Handle extract error reason.
 */
function extractErrorReason(error: unknown, context: ErrorContext): string {
  if (context.timedOut) {
    return `timeout abort after ${context.timeoutMs}ms`;
  }
  if (error instanceof Error) {
    const reasons = collectErrorDetails(error);
    if (reasons.length > 0) return reasons.join(" ");
    return pickReasonToken(error.message);
  }
  if (typeof error === "string") return pickReasonToken(error);
  try {
    return pickReasonToken(JSON.stringify(error));
  } catch {
    return pickReasonToken(String(error));
  }
}

/**
 * Handle extract error debug.
 */
function extractErrorDebug(error: unknown, context: ErrorContext): string {
  if (!error || typeof error !== "object") return "";
  const err = error as {
    name?: unknown;
    code?: unknown;
    cause?: { code?: unknown; message?: unknown } | unknown;
  };
  const parts: string[] = [];
  parts.push(`elapsed_ms=${context.elapsedMs}`);
  parts.push(`timeout_ms=${context.timeoutMs}`);
  if (context.timedOut) {
    parts.push("abort_source=timeout");
  }
  if (typeof err.name === "string" && err.name.trim()) {
    parts.push(`name=${err.name}`);
  }
  if (typeof err.code === "string" && err.code.trim()) {
    parts.push(`code=${err.code}`);
  }
  const cause = err.cause;
  if (cause && typeof cause === "object") {
    const causeObj = cause as { code?: unknown; message?: unknown };
    if (typeof causeObj.code === "string" && causeObj.code.trim()) {
      parts.push(`cause_code=${causeObj.code}`);
    }
    if (typeof causeObj.message === "string" && causeObj.message.trim()) {
      parts.push(`cause_message=${pickReasonToken(causeObj.message)}`);
    }
  }
  return parts.join("\n");
}

/**
 * Handle collect error details.
 */
function collectErrorDetails(error: Error): string[] {
  const details: string[] = [];
  const seen = new Set<string>();
  let current: unknown = error;
  let depth = 0;

  while (current && typeof current === "object" && depth < 3) {
    const err = current as { message?: string; code?: string; cause?: unknown };
    if (typeof err.code === "string") {
      if (!seen.has(err.code)) {
        seen.add(err.code);
        details.push(err.code);
      }
    }
    if (typeof err.message === "string" && err.message !== "fetch failed") {
      const token = pickReasonToken(err.message);
      if (token && !seen.has(token)) {
        seen.add(token);
        details.push(token);
      }
    }
    current = err.cause;
    depth += 1;
  }

  return details;
}

/**
 * Handle pick reason token.
 */
function pickReasonToken(message: string): string {
  const trimmed = message.trim();
  const split = trimmed.split("|", 1)[0];
  const firstLine = split.split("\n", 1)[0];
  return firstLine.trim();
}

/**
 * Handle parse retry after.
 */
function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (!Number.isNaN(seconds)) {
    return seconds * 1000;
  }
  const date = Date.parse(value);
  if (!Number.isNaN(date)) {
    const diff = date - Date.now();
    return diff > 0 ? diff : undefined;
  }
  return undefined;
}
