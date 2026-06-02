<script setup lang="ts">
/** Shared app navigation for the Vue SPA. */
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const githubUrl = "https://github.com/denikryt/PeerTube-browser";
const title = computed(() => {
  if (route.name === "search") return "Search";
  if (route.name === "channels") return "Channels";
  if (route.name === "video-detail") return "Video";
  if (route.name === "about") return "About";
  return "Home";
});
</script>

<template>
  <header class="videos-header">
    <div>
      <p class="eyebrow">PeerTube videos</p>
      <h1>{{ title }}</h1>
      <p class="subtitle"></p>
    </div>
    <nav class="header-nav" aria-label="Primary navigation">
      <RouterLink class="nav-link" to="/">Home</RouterLink>
      <RouterLink class="nav-link" to="/search">Search</RouterLink>
      <RouterLink class="nav-link" to="/channels">Channels</RouterLink>
      <RouterLink class="nav-link" to="/about">About</RouterLink>
      <a
        class="nav-link nav-link-icon"
        :href="githubUrl"
        target="_blank"
        rel="noopener"
        aria-label="Project repository on GitHub"
        title="Project repository on GitHub"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.77.6-3.35-1.34-3.35-1.34-.45-1.14-1.1-1.45-1.1-1.45-.9-.62.07-.61.07-.61 1 .07 1.52 1.03 1.52 1.03.9 1.55 2.35 1.1 2.93.84.09-.65.35-1.1.64-1.36-2.21-.25-4.54-1.11-4.54-4.95 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02A9.6 9.6 0 0 1 12 6.8c.85 0 1.7.11 2.5.33 1.9-1.29 2.74-1.02 2.74-1.02.56 1.38.21 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.85-2.33 4.7-4.55 4.95.36.32.68.93.68 1.87v2.78c0 .27.18.58.69.48A10 10 0 0 0 12 2z" />
        </svg>
      </a>
    </nav>
  </header>
</template>
