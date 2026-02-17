#!/usr/bin/env node

import { spawn } from "node:child_process";

const HELP_TEXT = `
Usage: npm run dev [-- [vite args...]] [--api-port <port>] [--api-base <url>]

Defaults:
  VITE_API_BASE=http://127.0.0.1:7071

Examples:
  npm run dev
  npm run dev -- --api-port 7070
  npm run dev -- --api-base http://127.0.0.1:9090
  npm run dev -- --port 5175 --strictPort --api-port 7070
`.trim();

function parsePort(raw) {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`Invalid port: ${raw}`);
  }
  return value;
}

function parseArgs(argv) {
  let apiBase = process.env.VITE_API_BASE || "";
  let apiPort = process.env.VITE_API_PORT || "7071";
  const viteArgs = [];

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      console.log(HELP_TEXT);
      process.exit(0);
    }
    if (arg === "--api-base") {
      const next = argv[index + 1];
      if (!next) throw new Error("Missing value for --api-base");
      apiBase = next;
      index += 1;
      continue;
    }
    if (arg.startsWith("--api-base=")) {
      apiBase = arg.slice("--api-base=".length);
      continue;
    }
    if (arg === "--api-port") {
      const next = argv[index + 1];
      if (!next) throw new Error("Missing value for --api-port");
      apiPort = String(parsePort(next));
      index += 1;
      continue;
    }
    if (arg.startsWith("--api-port=")) {
      apiPort = String(parsePort(arg.slice("--api-port=".length)));
      continue;
    }
    viteArgs.push(arg);
  }

  const normalizedApiBase = String(apiBase || "").trim();
  const finalApiBase =
    normalizedApiBase.length > 0 ? normalizedApiBase : `http://127.0.0.1:${parsePort(apiPort)}`;
  return { viteArgs, finalApiBase };
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
    VITE_API_BASE: parsed.finalApiBase,
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
