#!/usr/bin/env node

/**
 * Module `client/frontend/scripts/dev.mjs`: provide runtime functionality.
 */

import { spawn } from "node:child_process";

const HELP_TEXT = `
Usage: npm run dev [-- [vite args...]]
  [--client-api-base <url>]
  [--client-api-port <port>]

Defaults:
  VITE_CLIENT_API_BASE=http://127.0.0.1:7172

Examples:
  npm run dev
  npm run dev -- --client-api-port 7172
  npm run dev -- --client-api-base http://127.0.0.1:7072
`.trim();

/**
 * Handle parse port.
 */
function parsePort(raw) {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`Invalid port: ${raw}`);
  }
  return value;
}

/**
 * Handle normalize http base.
 */
function normalizeHttpBase(value) {
  const raw = String(value || "").trim();
  return raw.startsWith("http") ? raw : "";
}

/**
 * Handle parse args.
 */
function parseArgs(argv) {
  let clientApiBase = process.env.VITE_CLIENT_API_BASE || "";
  let clientApiPort =
    process.env.VITE_CLIENT_API_PORT ||
    "7172";

  const viteArgs = [];

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      console.log(HELP_TEXT);
      process.exit(0);
    }
    if (arg === "--client-api-base") {
      const next = argv[index + 1];
      if (!next) throw new Error("Missing value for --client-api-base");
      clientApiBase = next;
      index += 1;
      continue;
    }
    if (arg.startsWith("--client-api-base=")) {
      clientApiBase = arg.slice("--client-api-base=".length);
      continue;
    }
    if (arg === "--client-api-port") {
      const next = argv[index + 1];
      if (!next) throw new Error("Missing value for --client-api-port");
      clientApiPort = String(parsePort(next));
      index += 1;
      continue;
    }
    if (arg.startsWith("--client-api-port=")) {
      clientApiPort = String(parsePort(arg.slice("--client-api-port=".length)));
      continue;
    }
    viteArgs.push(arg);
  }

  const finalClientApiBase =
    normalizeHttpBase(clientApiBase) ||
    `http://127.0.0.1:${parsePort(clientApiPort)}`;
  return { viteArgs, finalClientApiBase };
}

let parsed;
try {
  parsed = parseArgs(process.argv.slice(2));
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  console.error("Use --help for usage.");
  process.exit(1);
}

const child = spawn("vite", parsed.viteArgs, {
  stdio: "inherit",
  env: {
    ...process.env,
    VITE_CLIENT_API_BASE: parsed.finalClientApiBase,
  },
});

child.on("error", (error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
