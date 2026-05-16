import { api, connectWS } from "./api.js";
import { Brain3D } from "./brain3d.js";
import { Brain2D } from "./brain2d.js";
import { runSplash } from "./splash.js";

const $ = (id) => document.getElementById(id);

const state = {
  graph: { nodes: [], edges: [] },
  mode: "3d",
  selectedId: null,
  brain3d: null,
  brain2d: null,
};

const NODE_COLORS = {
  task: "#85B7EB", idea: "#EF9F27", project: "#7F77DD",
  finance_event: "#5DCAA5", calendar_block: "#888888",
};

// ---------- bootstrap ----------

async function boot() {
  await runSplash($("splash"), $("splash-canvas"));
  $("splash").remove();

  state.brain3d = new Brain3D($("canvas-3d"));
  state.brain3d.onNodeClick = openSheet;
  state.brain3d.onNodeLongPress = openCtxMenu;
  state.brain3d.onDoubleTap = (lobe) => {
    if (state.brain3d.focusedLobe) state.brain3d.resetView();
    else if (lobe) state.brain3d.focusLobe(lobe);
  };

  bindUI();
  await refresh();
  connectWS(refresh);
}

// ---------- data ----------

async function refresh() {
  try {
    state.graph = await api.getGraph();
  } catch (e) {
    console.error(e);
    return;
  }
  render();
  await refreshActionable();
}

async function refreshActionable() {
  try {
    const list = await api.getActionable();
    renderActionable(list);
  } catch (e) { console.error(e); }
  renderInbox();
}

function render() {
  const visible = state.graph.nodes.filter((n) => n.status !== "deleted");
  $("node-count").textContent = visible.length;
  $("empty-hint").classList.toggle("hidden", visible.length > 0);

  if (state.mode === "3d") state.brain3d.update(state.graph);
  else {
    if (!state.brain2d) {
      state.brain2d = new Brain2D($("canvas-2d"));
      state.brain2d.onNodeClick = openSheet;
    }
    state.brain2d.update(state.graph);
  }
}

function renderActionable(list) {
  const ul = $("actionable-list");
  ul.innerHTML = "";
  if (!list.length) {
    ul.innerHTML = '<li style="background:transparent;color:#8c98a8">пока ничего</li>';
    return;
  }
  for (const n of list.slice(0, 6)) {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="dot" style="background:${NODE_COLORS[n.type] || "#fff"}"></span>
      <span class="title">${escapeHtml(n.title)}</span>
      <span class="meta">${n.required_time_minutes || 0}м</span>
    `;
    li.onclick = () => openSheet(n.id);
    ul.appendChild(li);
  }
}

function renderInbox() {
  const inbox = state.graph.nodes.filter((n) => n.status === "inbox");
  $("inbox-count").textContent = inbox.length;
  $("inbox-row").classList.toggle("hidden", inbox.length === 0);

  const ul = $("inbox-list");
  ul.innerHTML = "";
  for (const n of inbox) {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="dot" style="background:${NODE_COLORS[n.type] || "#fff"};width:8px;height:8px;border-radius:50%;align-self:center"></span>
      <span style="flex:1">${escapeHtml(n.title)}</span>
    `;
    li.onclick = () => { closeInbox(); openSheet(n.id); };
    ul.appendChild(li);
  }
}

// ---------- UI binding ----------

function bindUI() {
  $("btn-2d").onclick = () => setMode("2d");
  $("btn-3d").onclick = () => setMode("3d");
  $("btn-search").onclick = () => toggleSearch(true);
  $("search-close").onclick = () => toggleSearch(false);
  $("search-input").addEventListener("input", onSearch);

  $("fab").onclick = toggleInputRow;
  $("input-send").onclick = submitInput;
  $("input-field").addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitInput();
    if (e.key === "Escape") toggleInputRow();
  });

  $("inbox-toggle").onclick = openInbox;
  $("inbox-close").onclick = closeInbox;

  $("sheet-close").onclick = closeSheet;
  $("sheet-save").onclick  = saveSheet;
  $("sheet-done").onclick  = () => quickStatus("done");
  $("sheet-delete").onclick = deleteSheet;
  $("sheet-importance").addEventListener("input", (e) => {
    $("sheet-importance-val").textContent = e.target.value;
  });

  document.addEventListener("click", (e) => {
    const m = $("ctxmenu");
    if (!m.contains(e.target)) m.classList.add("hidden");
  });
  $("ctxmenu").querySelectorAll("button").forEach((b) => {
    b.onclick = async () => {
      const id = $("ctxmenu").dataset.nodeId;
      const action = b.dataset.action;
      $("ctxmenu").classList.add("hidden");
      if (!id) return;
      if (action === "delete") await api.deleteNode(id);
      else await api.updateNode(id, { status: action });
    };
  });

  // Keyboard: ⌘Z / Ctrl-Z = undo
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "z") {
      e.preventDefault();
      api.undo().catch((err) => console.warn("undo:", err.message));
    }
  });
}

function setMode(mode) {
  state.mode = mode;
  $("btn-2d").classList.toggle("active", mode === "2d");
  $("btn-3d").classList.toggle("active", mode === "3d");
  $("canvas-3d").classList.toggle("hidden", mode !== "3d");
  $("canvas-2d").classList.toggle("hidden", mode !== "2d");
  if (mode === "2d") {
    if (!state.brain2d) {
      state.brain2d = new Brain2D($("canvas-2d"));
      state.brain2d.onNodeClick = openSheet;
    }
    state.brain2d.update(state.graph);
    setTimeout(() => state.brain2d.resize(), 50);
  } else {
    state.brain3d.update(state.graph);
  }
}

// ---------- input row ----------

function toggleInputRow() {
  const row = $("input-row");
  const isHidden = row.classList.contains("hidden");
  row.classList.toggle("hidden");
  if (isHidden) {
    $("input-field").value = "";
    $("input-field").focus();
  }
}

async function submitInput() {
  const v = $("input-field").value.trim();
  if (!v) return;
  $("input-field").value = "";
  $("input-row").classList.add("hidden");
  try {
    await api.createNode({ type: "task", title: v, status: "inbox" });
  } catch (e) { alert(e.message); }
}

// ---------- search ----------

function toggleSearch(show) {
  $("search-bar").classList.toggle("hidden", !show);
  if (show) $("search-input").focus();
  else {
    $("search-input").value = "";
    state.brain3d.setSearchHighlight(null);
  }
}

function onSearch(e) {
  const q = e.target.value.trim().toLowerCase();
  if (!q) { state.brain3d.setSearchHighlight(null); return; }
  const matched = state.graph.nodes
    .filter((n) => (n.title || "").toLowerCase().includes(q))
    .map((n) => n.id);
  state.brain3d.setSearchHighlight(matched);
}

// ---------- inbox ----------

function openInbox() { $("inbox-panel").classList.remove("hidden"); }
function closeInbox() { $("inbox-panel").classList.add("hidden"); }

// ---------- sheet ----------

function openSheet(id) {
  const n = state.graph.nodes.find((x) => x.id === id);
  if (!n) return;
  state.selectedId = id;
  $("sheet-type").textContent = n.type;
  $("sheet-title").value = n.title || "";
  $("sheet-status").value = n.status || "inbox";
  $("sheet-importance").value = n.importance || 5;
  $("sheet-importance-val").textContent = n.importance || 5;
  $("sheet-energy").value = n.energy || "";
  $("sheet-time").value = n.required_time_minutes || 0;
  $("sheet-money").value = n.required_money || 0;
  $("sheet-deadline").value = n.deadline ? n.deadline.slice(0, 16) : "";
  $("sheet-tags").value = (n.tags || []).join(", ");
  $("sheet").classList.remove("hidden");
}

function closeSheet() {
  state.selectedId = null;
  $("sheet").classList.add("hidden");
}

async function saveSheet() {
  if (!state.selectedId) return;
  const patch = {
    title: $("sheet-title").value.trim(),
    status: $("sheet-status").value,
    importance: parseInt($("sheet-importance").value, 10),
    energy: $("sheet-energy").value || null,
    required_time_minutes: parseInt($("sheet-time").value || "0", 10),
    required_money: parseFloat($("sheet-money").value || "0"),
    deadline: $("sheet-deadline").value
      ? new Date($("sheet-deadline").value).toISOString()
      : null,
    tags: $("sheet-tags").value
      .split(",").map((s) => s.trim()).filter(Boolean),
  };
  try {
    await api.updateNode(state.selectedId, patch);
    closeSheet();
  } catch (e) { alert(e.message); }
}

async function quickStatus(status) {
  if (!state.selectedId) return;
  try {
    await api.updateNode(state.selectedId, { status });
    closeSheet();
  } catch (e) { alert(e.message); }
}

async function deleteSheet() {
  if (!state.selectedId) return;
  try {
    await api.deleteNode(state.selectedId);
    closeSheet();
  } catch (e) { alert(e.message); }
}

// ---------- context menu ----------

function openCtxMenu(id, x, y) {
  const m = $("ctxmenu");
  m.dataset.nodeId = id;
  m.style.left = Math.min(x, window.innerWidth - 160) + "px";
  m.style.top = Math.min(y, window.innerHeight - 140) + "px";
  m.classList.remove("hidden");
}

// ---------- util ----------

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

boot();
