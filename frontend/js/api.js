// REST + WebSocket wrapper.
// Single subscriber per event for simplicity; main.js wires the callback.

const base = "";

async function req(path, opts = {}) {
  const res = await fetch(base + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  getGraph:     ()           => req("/api/graph"),
  getActionable: (freeTime, strict) => {
    const qs = new URLSearchParams();
    if (freeTime != null) qs.set("free_time", freeTime);
    if (strict) qs.set("strict", "true");
    const q = qs.toString();
    return req("/api/actionable" + (q ? "?" + q : ""));
  },
  createNode:   (data)       => req("/api/nodes",          { method: "POST",   body: JSON.stringify(data) }),
  updateNode:   (id, patch)  => req(`/api/nodes/${id}`,    { method: "PATCH",  body: JSON.stringify(patch) }),
  deleteNode:   (id)         => req(`/api/nodes/${id}`,    { method: "DELETE" }),
  restoreNode:  (id)         => req(`/api/nodes/${id}/restore`, { method: "POST" }),
  createEdge:   (e)          => req("/api/edges",          { method: "POST",   body: JSON.stringify(e) }),
  deleteEdge:   (e)          => req("/api/edges",          { method: "DELETE", body: JSON.stringify(e) }),
  undo:         ()           => req("/api/undo",           { method: "POST" }),
  getAudit:     (limit=100)  => req(`/api/audit?limit=${limit}`),
};

export function connectWS(onChange) {
  let ws;
  let backoff = 500;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { backoff = 500; };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "graph_changed") onChange(msg);
      } catch {}
    };
    ws.onclose = () => {
      setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 5000);
    };
    ws.onerror = () => { try { ws.close(); } catch {} };
  };
  open();
  return { close: () => ws && ws.close() };
}
