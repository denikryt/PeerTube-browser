/**
 * Module `client/frontend/vite.config.ts`: provide runtime functionality.
 */

import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const rootDir = resolve(fileURLToPath(new URL(".", import.meta.url)));
const devPagesDir = resolve(rootDir, "dev-pages");

const devAboutPath = resolve(devPagesDir, "about.html");
const aboutTemplatePath = resolve(devPagesDir, "about.template.html");

const aboutSourcePath = existsSync(devAboutPath)
  ? "/dev-pages/about.html"
  : "/dev-pages/about.template.html";

const rewriteToVideos = new Set(["/videos", "/videos/"]);
const rewriteToAbout = new Set(["/about", "/about/", "/about.html"]);

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: "http://127.0.0.1:7172",
        changeOrigin: true,
        secure: true,
      },
      '/recommendations': {
        target: "http://127.0.0.1:7172",
        changeOrigin: true,
        secure: true,
      },
      '/videos/similar': {
        target: "http://127.0.0.1:7172",
        changeOrigin: true,
        secure: true,
      },
    },
    /**
     * Handle configure server.
     */
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (!req.url) return next();
        const urlPath = req.url.split("?")[0];
        if (rewriteToVideos.has(urlPath)) {
          req.url = "/videos.html";
        } else if (rewriteToAbout.has(urlPath)) {
          req.url = aboutSourcePath;
        }
        next();
      });
    },
  },
  preview: {
    port: 5173,
    /**
     * Handle configure preview server.
     */
    configurePreviewServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (!req.url) return next();
        const urlPath = req.url.split("?")[0];
        if (rewriteToVideos.has(urlPath)) {
          req.url = "/videos.html";
        } else if (rewriteToAbout.has(urlPath)) {
          req.url = aboutSourcePath;
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
        about: existsSync(devAboutPath)
          ? devAboutPath
          : aboutTemplatePath,
      },
    },
  },
});
