<script setup lang="ts">
/** Root app shell. It intentionally contains only shared chrome and routing. */
import AppHeader from "./components/AppHeader.vue";
</script>

<template>
  <div class="videos-app">
    <AppHeader />
    <RouterView />
  </div>
</template>
