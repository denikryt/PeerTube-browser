/**
 * Module `client/frontend/vite.config.ts`: provide runtime functionality.
 */

import { copyFileSync, existsSync, unlinkSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const rootDir = resolve(fileURLToPath(new URL(".", import.meta.url)));
const aboutOverridePath = resolve(rootDir, "about.html");
const aboutTemplatePath = resolve(rootDir, "about.template.html");

const rewriteToVideos = new Set(["/videos", "/videos/"]);
const rewriteToAbout = new Set(["/about", "/about/", "/about.html"]);

/**
 * Resolve the public path for the About page source used by dev and preview servers.
 */
function getAboutRequestPath() {
  return existsSync(aboutOverridePath) ? "/about.html" : "/about.template.html";
}

/**
 * Create a temporary root `about.html` entry for build output when only the template exists.
 */
function createAboutBuildFallback() {
  if (existsSync(aboutOverridePath)) {
    return () => {};
  }

  copyFileSync(aboutTemplatePath, aboutOverridePath);

  return () => {
    if (existsSync(aboutOverridePath)) {
      unlinkSync(aboutOverridePath);
    }
  };
}

/**
 * Clean up the temporary About entry created for production build fallback.
 */
function aboutBuildFallbackPlugin(cleanupAboutBuildFallback: () => void) {
  let cleanedUp = false;

  /**
   * Run cleanup only once regardless of which Rollup/Vite hook fires last.
   */
  function cleanup() {
    if (cleanedUp) {
      return;
    }

    cleanedUp = true;
    cleanupAboutBuildFallback();
  }

  return {
    name: "about-build-fallback",
    /**
     * Clean up early only if the build fails before bundle output completes.
     */
    buildEnd(error) {
      if (error) {
        cleanup();
      }
    },
    closeBundle() {
      cleanup();
    },
  };
}

export default defineConfig(({ command }) => {
  const cleanupAboutBuildFallback =
    command === "build" ? createAboutBuildFallback() : () => {};

  return {
    plugins: [aboutBuildFallbackPlugin(cleanupAboutBuildFallback)],
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
            req.url = getAboutRequestPath();
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
            req.url = getAboutRequestPath();
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
          about: aboutOverridePath,
        },
      },
    },
  };
});
