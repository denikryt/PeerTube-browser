/**
 * Vite configuration for the Vue 3 frontend application.
 *
 * The frontend is now a single browser SPA. Dev and preview servers rewrite
 * all non-API browser routes to index.html so Vue Router owns page routing,
 * while API traffic remains proxied to the Client backend only.
 */

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

const rootDir = resolve(fileURLToPath(new URL(".", import.meta.url)));

/** Return true for browser routes that the SPA should handle. */
function shouldRewriteToIndex(url: string | undefined) {
  if (!url) return false;
  const path = url.split("?")[0];
  if (!path || path === "/") return false;
  if (path.startsWith("/api") || path.startsWith("/assets") || path.startsWith("/favicon")) {
    return false;
  }
  return !path.includes(".");
}

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:7172",
        changeOrigin: true,
        secure: true
      }
    },
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (shouldRewriteToIndex(req.url)) {
          req.url = "/index.html";
        }
        next();
      });
    }
  },
  preview: {
    port: 5173,
    configurePreviewServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (shouldRewriteToIndex(req.url)) {
          req.url = "/index.html";
        }
        next();
      });
    }
  },
  build: {
    rollupOptions: {
      input: resolve(rootDir, "index.html")
    }
  }
});
