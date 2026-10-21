<script setup lang="ts">
/** Root app shell that caches only the Home route instance across detail trips. */
import { computed } from "vue";
import { useRoute } from "vue-router";
import AppHeader from "./components/AppHeader.vue";

const route = useRoute();
const shellClass = computed(() => route.name === "video-detail" ? "video-page" : "videos-app");
</script>

<template>
  <div :class="shellClass">
    <AppHeader />
    <RouterView v-slot="{ Component }">
      <KeepAlive>
        <component :is="Component" v-if="route.name === 'home'" />
      </KeepAlive>
      <component :is="Component" v-if="route.name !== 'home'" />
    </RouterView>
  </div>
</template>
