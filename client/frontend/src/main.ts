/**
 * Vue application entrypoint.
 *
 * This module owns only application bootstrap. Routing, data loading, and
 * rendering live in dedicated router, composable, view, and component modules.
 */

import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import "./videos.css";
import "./video.css";
import "./channels.css";

createApp(App).use(router).mount("#app");
