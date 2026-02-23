/**
 * DEV_MAP interactive viewer logic.
 * Loads `DEV_MAP.json`, renders hierarchy, and provides status filters and ID navigation.
 */

/** @type {{milestones: Array<object>} | null} */
let mapData = null;

/** @type {Map<string, HTMLElement>} */
const idIndex = new Map();

/**
 * Parse and set map payload from raw text.
 * @param {string} raw
 * @throws {Error}
 */
function setMapFromRaw(raw) {
  const parsed = JSON.parse(raw);
  if (!parsed || !Array.isArray(parsed.milestones)) {
    throw new Error("Invalid DEV_MAP format: expected milestones array.");
  }
  mapData = parsed;
  renderMap();
}

/**
 * Load DEV_MAP from relative `DEV_MAP.json` URL.
 * @returns {Promise<void>}
 */
async function loadMapFromFetch() {
  const response = await fetch("./DEV_MAP.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const raw = await response.text();
  setMapFromRaw(raw);
}

/**
 * Return true when a node with this status should be visible.
 * @param {string} status
 * @returns {boolean}
 */
function statusVisible(status) {
  if (typeof status !== "string" || status.length === 0) {
    return true;
  }
  const planned = document.getElementById("filter-planned").checked;
  const done = document.getElementById("filter-done").checked;
  if (status === "Planned") {
    return planned;
  }
  if (status === "Done") {
    return done;
  }
  return false;
}

/**
 * Build a status badge element.
 * @param {string} status
 * @returns {HTMLSpanElement}
 */
function createStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status ${status === "Done" ? "status-done" : "status-planned"}`;
  badge.textContent = status;
  return badge;
}

/**
 * Register a node in id index for direct navigation.
 * @param {string} id
 * @param {HTMLElement} element
 */
function registerId(id, element) {
  const key = String(id).trim().toLowerCase();
  if (!key) {
    return;
  }
  idIndex.set(key, element);
}

/**
 * Render full map tree.
 */
function renderMap() {
  const root = document.getElementById("map-root");
  root.innerHTML = "";
  idIndex.clear();

  if (!mapData || !Array.isArray(mapData.milestones)) {
    root.textContent = "Invalid DEV_MAP payload.";
    return;
  }

  const visibleMilestones = mapData.milestones;

  if (visibleMilestones.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No milestones.";
    root.appendChild(empty);
    return;
  }

  for (const milestone of visibleMilestones) {
    const milestoneNode = renderMilestone(milestone);
    if (milestoneNode) {
      root.appendChild(milestoneNode);
    }
  }
}

/**
 * Render milestone node.
 * @param {any} milestone
 * @returns {HTMLElement | null}
 */
function renderMilestone(milestone) {
  const details = document.createElement("details");
  details.open = true;
  details.className = "node";
  details.dataset.nodeId = milestone.id;

  const summary = document.createElement("summary");
  const id = document.createElement("span");
  id.className = "node-id";
  id.textContent = milestone.id;
  summary.appendChild(id);
  summary.appendChild(document.createTextNode(milestone.title));
  details.appendChild(summary);
  registerId(milestone.id, summary);

  if (typeof milestone.goal === "string" && milestone.goal.trim().length > 0) {
    const meta = document.createElement("div");
    meta.className = "milestone-meta";
    meta.textContent = `Goal: ${milestone.goal.trim()}`;
    details.appendChild(meta);
  }

  const features = Array.isArray(milestone.features) ? milestone.features : [];
  const visibleFeatures = features.filter((feature) => statusVisible(feature.status));

  if (visibleFeatures.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No features";
    details.appendChild(empty);
  } else {
    for (const feature of visibleFeatures) {
      const featureNode = renderFeature(feature);
      if (featureNode) {
        details.appendChild(featureNode);
      }
    }
  }

  const standaloneIssues = Array.isArray(milestone.standalone_issues) ? milestone.standalone_issues : [];
  const visibleStandaloneIssues = standaloneIssues.filter((item) => statusVisible(item.status));
  if (visibleStandaloneIssues.length > 0) {
    details.appendChild(renderStandaloneIssueGroup(visibleStandaloneIssues));
  }

  const nonFeatures = Array.isArray(milestone.non_feature_items) ? milestone.non_feature_items : [];
  if (nonFeatures.length > 0) {
    details.appendChild(renderNonFeatureGroup(nonFeatures));
  }

  return details;
}

/**
 * Render feature node.
 * @param {any} feature
 * @returns {HTMLElement | null}
 */
function renderFeature(feature) {
  const details = document.createElement("details");
  details.className = "node";
  details.dataset.nodeId = feature.id;

  const summary = document.createElement("summary");
  const id = document.createElement("span");
  id.className = "node-id";
  id.textContent = feature.id;
  summary.appendChild(id);
  summary.appendChild(document.createTextNode(feature.title));
  summary.appendChild(createStatusBadge(feature.status));
  details.appendChild(summary);
  registerId(feature.id, summary);

  const ref = document.createElement("div");
  ref.className = "muted";
  const track = typeof feature.track === "string" ? feature.track : null;
  const optional = feature.optional === true ? "Optional" : null;
  const ghText = feature.gh_issue_number ? `GH #${feature.gh_issue_number}` : "GH issue: not materialized";
  const refParts = [track, optional, ghText].filter(Boolean);
  ref.textContent = refParts.join(" | ");
  details.appendChild(ref);

  if (typeof feature.note === "string" && feature.note.trim().length > 0) {
    const note = document.createElement("div");
    note.className = "muted";
    note.textContent = `Note: ${feature.note.trim()}`;
    details.appendChild(note);
  }

  const issues = Array.isArray(feature.issues) ? feature.issues : [];
  const visibleIssues = issues.filter((issue) => statusVisible(issue.status));

  if (visibleIssues.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No issues";
    details.appendChild(empty);
    return details;
  }

  for (const issue of visibleIssues) {
    const issueNode = renderIssue(issue);
    if (issueNode) {
      details.appendChild(issueNode);
    }
  }

  return details;
}

/**
 * Render collapsible non-feature item group for one milestone.
 * @param {Array<any>} items
 * @returns {HTMLElement}
 */
function renderNonFeatureGroup(items) {
  const wrap = document.createElement("details");
  wrap.className = "node";
  wrap.open = false;

  const summary = document.createElement("summary");
  summary.textContent = "Non-feature items";
  wrap.appendChild(summary);

  for (const item of items) {
    wrap.appendChild(renderNonFeatureItem(item));
  }

  return wrap;
}

/**
 * Render collapsible standalone issue group for one milestone.
 * @param {Array<any>} items
 * @returns {HTMLElement}
 */
function renderStandaloneIssueGroup(items) {
  const wrap = document.createElement("details");
  wrap.className = "node";
  wrap.open = false;

  const summary = document.createElement("summary");
  summary.textContent = "Standalone issues";
  wrap.appendChild(summary);

  for (const issue of items) {
    wrap.appendChild(renderStandaloneIssue(issue));
  }

  return wrap;
}

/**
 * Render standalone issue node.
 * @param {any} issue
 * @returns {HTMLElement}
 */
function renderStandaloneIssue(issue) {
  const details = document.createElement("details");
  details.className = "node";
  details.dataset.nodeId = issue.id;

  const summary = document.createElement("summary");
  const id = document.createElement("span");
  id.className = "node-id";
  id.textContent = issue.id;
  summary.appendChild(id);
  summary.appendChild(document.createTextNode(issue.title || "Standalone issue"));
  summary.appendChild(createStatusBadge(issue.status || "Planned"));
  details.appendChild(summary);
  registerId(issue.id, summary);

  const ref = document.createElement("div");
  ref.className = "muted";
  ref.textContent = issue.gh_issue_number ? `GH #${issue.gh_issue_number}` : "GH issue: not materialized";
  details.appendChild(ref);

  const tasks = Array.isArray(issue.tasks) ? issue.tasks : [];
  const visibleTasks = tasks.filter((task) => statusVisible(task.status));

  if (visibleTasks.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No tasks";
    details.appendChild(empty);
    return details;
  }

  for (const task of visibleTasks) {
    details.appendChild(renderTask(task));
  }

  return details;
}

/**
 * Render non-feature milestone item (checkpoint or needs-split marker).
 * @param {any} item
 * @returns {HTMLElement}
 */
function renderNonFeatureItem(item) {
  const wrap = document.createElement("div");
  wrap.className = "non-feature-item";

  const label = document.createElement("span");
  const needsSplit = item && item.classification === "needs_split";
  label.className = needsSplit ? "label label-needs-split" : "label";
  label.textContent = needsSplit ? "needs_split" : "not_feature";
  wrap.appendChild(label);

  const idText = typeof item.id === "string" ? `${item.id}: ` : "";
  const titleText = typeof item.title === "string" ? item.title : "Untitled";
  wrap.appendChild(document.createTextNode(`${idText}${titleText}`));

  if (typeof item.reason === "string" && item.reason.trim().length > 0) {
    const reason = document.createElement("div");
    reason.className = "muted";
    reason.textContent = `Reason: ${item.reason.trim()}`;
    wrap.appendChild(reason);
  }

  return wrap;
}

/**
 * Render issue node.
 * @param {any} issue
 * @returns {HTMLElement | null}
 */
function renderIssue(issue) {
  const details = document.createElement("details");
  details.className = "node";
  details.dataset.nodeId = issue.id;

  const summary = document.createElement("summary");
  const id = document.createElement("span");
  id.className = "node-id";
  id.textContent = issue.id;
  summary.appendChild(id);
  summary.appendChild(document.createTextNode(issue.title));
  summary.appendChild(createStatusBadge(issue.status));
  details.appendChild(summary);
  registerId(issue.id, summary);

  const ref = document.createElement("div");
  ref.className = "muted";
  ref.textContent = issue.gh_issue_number ? `GH #${issue.gh_issue_number}` : "GH issue: not materialized";
  details.appendChild(ref);

  const tasks = Array.isArray(issue.tasks) ? issue.tasks : [];
  const visibleTasks = tasks.filter((task) => statusVisible(task.status));

  if (visibleTasks.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No tasks";
    details.appendChild(empty);
    return details;
  }

  for (const task of visibleTasks) {
    const taskNode = renderTask(task);
    details.appendChild(taskNode);
  }

  return details;
}

/**
 * Render task leaf node.
 * @param {any} task
 * @returns {HTMLElement}
 */
function renderTask(task) {
  const wrap = document.createElement("div");
  wrap.className = "node";

  const title = document.createElement("div");
  title.dataset.nodeId = task.id;
  const id = document.createElement("span");
  id.className = "node-id";
  id.textContent = task.id;
  title.appendChild(id);
  title.appendChild(document.createTextNode(task.title));
  title.appendChild(createStatusBadge(task.status));
  wrap.appendChild(title);
  registerId(task.id, title);

  const hasDate = typeof task.date === "string" && task.date.trim().length > 0;
  const hasTime = typeof task.time === "string" && task.time.trim().length > 0;
  if (hasDate || hasTime) {
    const dt = document.createElement("div");
    dt.className = "muted";
    dt.textContent = `Timestamp: ${[task.date, task.time].filter(Boolean).join(" ")}`;
    wrap.appendChild(dt);
  }

  if (typeof task.summary === "string" && task.summary.trim().length > 0) {
    const summary = document.createElement("div");
    summary.className = "muted";
    summary.textContent = task.summary.trim();
    wrap.appendChild(summary);
  }

  return wrap;
}

/**
 * Expand all details nodes.
 * @param {boolean} state
 */
function setExpandAll(state) {
  document.querySelectorAll("details").forEach((node) => {
    node.open = state;
  });
}

/**
 * Navigate to node id and expand ancestors.
 */
function goToId() {
  const input = document.getElementById("goto-input");
  const msg = document.getElementById("goto-msg");
  const needle = input.value.trim().toLowerCase();

  document.querySelectorAll(".hit").forEach((el) => el.classList.remove("hit"));

  if (!needle) {
    msg.textContent = "Enter a node id.";
    return;
  }

  const target = idIndex.get(needle);
  if (!target) {
    msg.textContent = `ID not found: ${input.value}`;
    return;
  }

  let parent = target.parentElement;
  while (parent) {
    if (parent.tagName === "DETAILS") {
      parent.open = true;
    }
    parent = parent.parentElement;
  }

  target.classList.add("hit");
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  msg.textContent = "";
  window.location.hash = input.value;
}

/**
 * Load DEV_MAP and initialize controls.
 */
async function init() {
  const root = document.getElementById("map-root");

  try {
    await loadMapFromFetch();
  } catch (error) {
    root.innerHTML = "";
    const msg = document.createElement("div");
    msg.className = "empty";
    msg.textContent = `Failed to load DEV_MAP.json: ${error.message}`;
    root.appendChild(msg);
    return;
  }

  document.getElementById("filter-planned").addEventListener("change", renderMap);
  document.getElementById("filter-done").addEventListener("change", renderMap);
  document.getElementById("expand-all").addEventListener("click", () => setExpandAll(true));
  document.getElementById("collapse-all").addEventListener("click", () => setExpandAll(false));
  document.getElementById("goto-btn").addEventListener("click", goToId);
  document.getElementById("goto-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      goToId();
    }
  });

  if (window.location.hash.length > 1) {
    document.getElementById("goto-input").value = window.location.hash.slice(1);
    goToId();
  }
}

init();
