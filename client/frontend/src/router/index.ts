/**
 * Vue Router configuration for the canonical frontend routes.
 *
 * Legacy HTML entrypoints are intentionally absent. Video identity is encoded
 * as `/video/:host/:id` because backend lookup remains host-scoped.
 */

import { createRouter, createWebHistory } from "vue-router";
import HomeView from "../views/HomeView.vue";
import SearchView from "../views/SearchView.vue";
import ChannelsView from "../views/ChannelsView.vue";
import VideoDetailView from "../views/VideoDetailView.vue";
import AboutView from "../views/AboutView.vue";

export const router = createRouter({
  history: createWebHistory(),
  linkActiveClass: "active",
  linkExactActiveClass: "active",
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/search", name: "search", component: SearchView },
    { path: "/channels", name: "channels", component: ChannelsView },
    { path: "/video/:host/:id", name: "video-detail", component: VideoDetailView },
    { path: "/about", name: "about", component: AboutView }
  ],
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 };
  }
});
