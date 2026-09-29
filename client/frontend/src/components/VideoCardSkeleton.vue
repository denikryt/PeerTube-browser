<script setup lang="ts">
/**
 * Reserve the exact visual footprint of a feed card while its metadata arrives.
 *
 * The component is decorative: the containing feed remains the only loading
 * status owner, while this skeleton prevents the grid from jumping when rows
 * replace the initial request state.
 */
</script>

<template>
  <article class="video-card-skeleton" aria-hidden="true">
    <div class="video-card-skeleton-thumb"></div>
    <div class="video-card-skeleton-meta">
      <span class="video-card-skeleton-avatar"></span>
      <span class="video-card-skeleton-lines">
        <span class="video-card-skeleton-line video-card-skeleton-line-title"></span>
        <span class="video-card-skeleton-line video-card-skeleton-line-meta"></span>
      </span>
    </div>
  </article>
</template>
