<script setup lang="ts">
/** Shared status presentation for loading, empty, and error states. */
defineProps<{ kind?: "loading" | "empty" | "error"; message: string }>();
</script>

<template>
  <div :class="kind === 'error' ? 'error' : 'loading'" role="status">{{ message }}</div>
</template>
