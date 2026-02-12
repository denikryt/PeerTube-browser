import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const rootDir = resolve(fileURLToPath(new URL(".", import.meta.url)));

const rewriteToVideos = new Set(["/videos", "/videos/"]);
const rewriteToChangelog = new Set(["/changelog", "/changelog/"]);

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: "http://127.0.0.1:7070",
        changeOrigin: true,
        secure: true,
      },
    },
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (!req.url) return next();
        const urlPath = req.url.split("?")[0];
        if (rewriteToVideos.has(urlPath)) {
          req.url = "/videos.html";
        } else if (rewriteToChangelog.has(urlPath)) {
          req.url = "/changelog.html";
        }
        next();
      });
    },
  },
  preview: {
    port: 5173,
    configurePreviewServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (!req.url) return next();
        const urlPath = req.url.split("?")[0];
        if (rewriteToVideos.has(urlPath)) {
          req.url = "/videos.html";
        } else if (rewriteToChangelog.has(urlPath)) {
          req.url = "/changelog.html";
        }
        next();
      });
    },
  },
  build: {
    rollupOptions: {
      input: {
        index: resolve(rootDir, "index.html"),
        videos: resolve(rootDir, "videos.html"),
        video: resolve(rootDir, "video-page.html"),
        channels: resolve(rootDir, "channels.html"),
        changelog: resolve(rootDir, "changelog.html"),
        about: resolve(rootDir, "about.html"),
      },
    },
  },
});
