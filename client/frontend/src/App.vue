<script setup lang="ts">
/** Root app shell. It keeps the legacy route shell class for the video detail page. */
import { computed } from "vue";
import { useRoute } from "vue-router";
import AppHeader from "./components/AppHeader.vue";

const route = useRoute();
const shellClass = computed(() => route.name === "video-detail" ? "video-page" : "videos-app");
</script>

<template>
  <div :class="shellClass">
    <AppHeader />
    <RouterView />
  </div>
</template>
