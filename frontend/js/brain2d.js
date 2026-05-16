// Cytoscape.js fallback. Loaded globally via <script>; we just use window.cytoscape.

const NODE_COLORS = {
  task:           "#85B7EB",
  idea:           "#EF9F27",
  project:        "#7F77DD",
  finance_event:  "#5DCAA5",
  calendar_block: "#888888",
};

export class Brain2D {
  constructor(host) {
    this.host = host;
    this.cy = null;
    this.onNodeClick = null;
    this._ensureContainer();
  }

  _ensureContainer() {
    this.host.style.position = "absolute";
    this.host.style.inset = "0";
  }

  update(graphData) {
    const nodes = graphData.nodes
      .filter((n) => n.status !== "deleted")
      .map((n) => ({
        data: {
          id: n.id, label: n.title || "(untitled)",
          type: n.type || "task", status: n.status,
        },
      }));
    const edges = graphData.edges.map((e, i) => ({
      data: { id: `e${i}`, source: e.from, target: e.to, type: e.type },
    }));

    if (!this.cy) {
      if (!window.cytoscape) {
        this.host.innerHTML = '<div style="padding:24px;color:#8c98a8;">Cytoscape не загружен</div>';
        return;
      }
      this.cy = window.cytoscape({
        container: this.host,
        elements: [...nodes, ...edges],
        layout: { name: "cose", animate: false, padding: 30 },
        style: [
          {
            selector: "node",
            style: {
              "background-color": (ele) => NODE_COLORS[ele.data("type")] || "#ccc",
              label: "data(label)",
              color: "#e9eef5",
              "font-size": 10,
              "text-valign": "bottom",
              "text-margin-y": 6,
              "text-outline-color": "#0a0e13",
              "text-outline-width": 2,
              opacity: (ele) => ele.data("status") === "done" ? 0.4 : 1.0,
            },
          },
          {
            selector: "edge",
            style: {
              width: 1.2,
              "line-color": (ele) => ele.data("type") === "BLOCKS" ? "#E74C3C" : "#b8d4ff",
              "curve-style": "haystack",
              opacity: 0.4,
            },
          },
        ],
      });
      this.cy.on("tap", "node", (ev) => {
        if (this.onNodeClick) this.onNodeClick(ev.target.id());
      });
    } else {
      this.cy.elements().remove();
      this.cy.add([...nodes, ...edges]);
      this.cy.layout({ name: "cose", animate: false, padding: 30 }).run();
    }
  }

  resize() { this.cy && this.cy.resize(); }
  dispose() { this.cy && this.cy.destroy(); this.cy = null; }
}
