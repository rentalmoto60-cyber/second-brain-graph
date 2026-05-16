// Three.js brain visualization: procedural brain mesh + InstancedMesh nodes +
// LineSegments edges + raycaster interaction. Falls back gracefully if no GLB
// is available at /static/assets/brain.glb.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const NODE_COLORS = {
  task:           0x85B7EB,
  idea:           0xEF9F27,
  project:        0x7F77DD,
  finance_event:  0x5DCAA5,
  calendar_block: 0x888888,
};
const EDGE_COLORS = {
  BLOCKS:       0xE74C3C,
  PART_OF:      0xb8d4ff,
  FUNDED_BY:    0x5DCAA5,
  CONTEXT_LINK: 0xb8d4ff,
};

export class Brain3D {
  constructor(host) {
    this.host = host;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    this.camera.position.set(0, 0, 7);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    host.appendChild(this.renderer.domElement);

    // Lights
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.45));
    const dir = new THREE.DirectionalLight(0xffffff, 0.7); dir.position.set(3, 4, 5); this.scene.add(dir);
    const rim = new THREE.DirectionalLight(0x6ea8ff, 0.3); rim.position.set(-4, 1, -3); this.scene.add(rim);
    const inner = new THREE.PointLight(0xff9fc4, 0.5, 4); inner.position.set(0, 0, 0); this.scene.add(inner);

    // Brain
    this.brainGroup = new THREE.Group();
    this.scene.add(this.brainGroup);

    // Nodes / edges
    this.nodesByType = {};          // type → { mesh: InstancedMesh, ids: [], capacity }
    this.edgeLines = null;
    this.idIndex = new Map();       // node_id → { type, instanceId, pos }
    this.nodes = [];
    this.edges = [];

    // Highlight state
    this.hoverId = null;
    this.searchHighlight = null;    // Set<id> or null
    this.focusedLobe = null;        // string lobe name or null

    // Interaction state
    this.rot = { x: 0, y: 0 };
    this.targetRot = { x: 0, y: 0 };
    this.autoRotate = true;
    this.zoom = 7;
    this.targetZoom = 7;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();

    this._setupBrainMesh();
    this._setupInteraction();
    this._onResize = this._onResize.bind(this);
    window.addEventListener("resize", this._onResize);
    this._onResize();

    this.onNodeClick = null;       // (id) => void
    this.onNodeLongPress = null;   // (id, clientX, clientY) => void
    this.onDoubleTap = null;       // (lobe|null) => void

    this._tick = this._tick.bind(this);
    this._tick();
  }

  // ---------- brain mesh ----------

  _setupBrainMesh() {
    // Try to load a GLB; fall back to procedural if missing.
    const loader = new GLTFLoader();
    loader.load(
      "/static/assets/brain.glb",
      (gltf) => {
        const root = gltf.scene;
        this._normalizeAndAddBrain(root);
      },
      undefined,
      () => {
        this._buildProceduralBrain();
      }
    );
    // Build procedural immediately so the user sees something while GLB loads.
    this._buildProceduralBrain();
  }

  _normalizeAndAddBrain(obj) {
    // Center & scale to fit a -1..1 box
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    obj.position.sub(center);
    obj.scale.multiplyScalar(2.0 / maxDim);

    // Replace materials with our brain material
    obj.traverse((c) => {
      if (c.isMesh) {
        c.material = this._brainMaterial();
      }
    });
    // Remove any previous procedural brain
    this._clearBrainGroup();
    this.brainGroup.add(obj);
    this._addBrainEdges(obj);
  }

  _brainMaterial() {
    return new THREE.MeshPhysicalMaterial({
      color: 0xd49ba8,
      transparent: true,
      opacity: 0.32,
      transmission: 0.5,
      roughness: 0.4,
      metalness: 0.05,
      thickness: 0.4,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
  }

  _clearBrainGroup() {
    while (this.brainGroup.children.length) {
      const c = this.brainGroup.children.pop();
      c.traverse?.((o) => { o.geometry?.dispose?.(); o.material?.dispose?.(); });
    }
  }

  _buildProceduralBrain() {
    this._clearBrainGroup();
    // Two hemispheres: ellipsoids displaced by sinusoidal noise to mimic sulci.
    const geom = new THREE.IcosahedronGeometry(1.0, 6);
    this._displaceForBrain(geom);
    const mat = this._brainMaterial();

    const left = new THREE.Mesh(geom, mat);
    left.scale.set(0.55, 0.7, 0.95);
    left.position.x = -0.42;
    const right = left.clone();
    right.position.x = 0.42;
    right.scale.x *= -1; // mirror

    const cerebellum = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.45, 3),
      mat,
    );
    cerebellum.position.set(0, -0.55, -0.55);
    cerebellum.scale.set(1, 0.55, 0.7);

    this.brainGroup.add(left);
    this.brainGroup.add(right);
    this.brainGroup.add(cerebellum);

    this._addBrainEdges(left, 0xffd4d8);
    this._addBrainEdges(right, 0xffd4d8);
  }

  _displaceForBrain(geom) {
    const pos = geom.attributes.position;
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      const n = v.clone().normalize();
      // multi-octave sin noise → faux gyri
      const d =
        0.08 * Math.sin(n.x * 7 + n.y * 11) +
        0.06 * Math.sin(n.y * 13 + n.z * 9) +
        0.05 * Math.sin(n.z * 17 + n.x * 5) +
        0.03 * Math.sin((n.x + n.y + n.z) * 23);
      v.addScaledVector(n, d);
      pos.setXYZ(i, v.x, v.y, v.z);
    }
    pos.needsUpdate = true;
    geom.computeVertexNormals();
  }

  _addBrainEdges(obj, color = 0xffd4d8) {
    obj.traverse?.((c) => {
      if (!c.isMesh) return;
      const eg = new THREE.EdgesGeometry(c.geometry, 25);
      const em = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.18 });
      const lines = new THREE.LineSegments(eg, em);
      c.add(lines);
    });
  }

  // ---------- nodes & edges ----------

  update(graphData) {
    this.nodes = graphData.nodes.filter((n) => n.status !== "deleted");
    this.edges = graphData.edges;
    this._rebuildNodes();
    this._rebuildEdges();
  }

  _rebuildNodes() {
    // Clear previous instanced meshes
    for (const k of Object.keys(this.nodesByType)) {
      const grp = this.nodesByType[k];
      this.scene.remove(grp.mesh);
      grp.mesh.geometry.dispose();
      grp.mesh.material.dispose();
    }
    this.nodesByType = {};
    this.idIndex.clear();

    const byType = {};
    for (const n of this.nodes) {
      const t = n.type || "task";
      (byType[t] ||= []).push(n);
    }

    const sphere = new THREE.SphereGeometry(0.04, 10, 10);
    const dummy = new THREE.Object3D();
    const now = Date.now();

    for (const [type, list] of Object.entries(byType)) {
      const mat = new THREE.MeshStandardMaterial({
        color: NODE_COLORS[type] || 0xffffff,
        emissive: NODE_COLORS[type] || 0xffffff,
        emissiveIntensity: 0.4,
        transparent: true,
        opacity: 0.95,
      });
      const mesh = new THREE.InstancedMesh(sphere, mat, Math.max(list.length, 1));
      mesh.frustumCulled = false;
      const colors = new Float32Array(list.length * 3);

      list.forEach((n, i) => {
        const p = n.position || { x: 0, y: 0, z: 0 };
        const importance = n.importance || 5;
        let scale = (0.6 + importance * 0.1);

        const isFresh = this._isFresh(n.created_at, now);
        if (isFresh) scale *= 1.6;
        if (n.status === "done") {
          mesh.material.opacity = 0.95; // global; per-instance opacity not supported easily
        }
        dummy.position.set(p.x, p.y, p.z);
        dummy.scale.setScalar(scale);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);

        const c = new THREE.Color(NODE_COLORS[type] || 0xffffff);
        if (n.status === "done") c.multiplyScalar(0.35);
        if (n.status === "inbox") c.lerp(new THREE.Color(0xffffff), 0.6);
        colors[i * 3]     = c.r;
        colors[i * 3 + 1] = c.g;
        colors[i * 3 + 2] = c.b;

        this.idIndex.set(n.id, { type, instanceId: i, pos: p, fresh: isFresh, status: n.status });
      });

      mesh.instanceColor = new THREE.InstancedBufferAttribute(colors, 3);
      mesh.instanceMatrix.needsUpdate = true;
      this.scene.add(mesh);
      this.nodesByType[type] = { mesh, ids: list.map((n) => n.id), capacity: list.length };
    }
  }

  _isFresh(createdAt, now) {
    if (!createdAt) return false;
    const t = Date.parse(createdAt);
    return !isNaN(t) && now - t < 24 * 3600 * 1000;
  }

  _rebuildEdges() {
    if (this.edgeLines) {
      this.scene.remove(this.edgeLines);
      this.edgeLines.geometry.dispose();
      this.edgeLines.material.dispose();
      this.edgeLines = null;
    }
    if (!this.edges.length) return;

    const positions = [];
    const colors = [];
    for (const e of this.edges) {
      const a = this.idIndex.get(e.from);
      const b = this.idIndex.get(e.to);
      if (!a || !b) continue;
      positions.push(a.pos.x, a.pos.y, a.pos.z, b.pos.x, b.pos.y, b.pos.z);
      const c = new THREE.Color(EDGE_COLORS[e.type] || 0xb8d4ff);
      colors.push(c.r, c.g, c.b, c.r, c.g, c.b);
    }
    if (!positions.length) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    const m = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.28,
    });
    this.edgeLines = new THREE.LineSegments(g, m);
    this.scene.add(this.edgeLines);
  }

  // ---------- interaction ----------

  _setupInteraction() {
    const el = this.renderer.domElement;
    el.style.touchAction = "none";

    let dragging = false;
    let lastX = 0, lastY = 0;
    let downAt = 0;
    let longPressTimer = null;
    let lastTapAt = 0;
    let movedDuringDrag = false;

    const start = (x, y) => {
      dragging = true; lastX = x; lastY = y; movedDuringDrag = false;
      downAt = Date.now();
      this.autoRotate = false;
      const hit = this._raycastNode(x, y);
      longPressTimer = setTimeout(() => {
        if (hit && this.onNodeLongPress) {
          this.onNodeLongPress(hit, x, y);
          longPressTimer = null;
        }
      }, 500);
    };
    const move = (x, y) => {
      if (!dragging) return;
      const dx = x - lastX, dy = y - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 4) {
        movedDuringDrag = true;
        if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; }
      }
      this.targetRot.y += dx * 0.005;
      this.targetRot.x += dy * 0.005;
      this.targetRot.x = Math.max(-1.2, Math.min(1.2, this.targetRot.x));
      lastX = x; lastY = y;
    };
    const end = (x, y) => {
      if (!dragging) return;
      dragging = false;
      if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; }
      const duration = Date.now() - downAt;
      if (!movedDuringDrag && duration < 300) {
        const now = Date.now();
        const isDouble = now - lastTapAt < 300;
        lastTapAt = now;
        const hit = this._raycastNode(x, y);
        if (isDouble) {
          if (this.onDoubleTap) this.onDoubleTap(hit ? null : this._lobeAt(x, y));
        } else if (hit && this.onNodeClick) {
          this.onNodeClick(hit);
        }
      }
    };

    el.addEventListener("pointerdown", (e) => { start(e.clientX, e.clientY); el.setPointerCapture(e.pointerId); });
    el.addEventListener("pointermove", (e) => move(e.clientX, e.clientY));
    el.addEventListener("pointerup",   (e) => end(e.clientX, e.clientY));
    el.addEventListener("pointercancel", () => { dragging = false; if (longPressTimer) clearTimeout(longPressTimer); });

    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.targetZoom = Math.max(3, Math.min(15, this.targetZoom + e.deltaY * 0.005));
    }, { passive: false });
  }

  _raycastNode(clientX, clientY) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);

    let best = null;
    let bestDist = Infinity;
    for (const grp of Object.values(this.nodesByType)) {
      const hits = this.raycaster.intersectObject(grp.mesh, false);
      for (const h of hits) {
        if (h.distance < bestDist) {
          bestDist = h.distance;
          best = grp.ids[h.instanceId];
        }
      }
    }
    return best;
  }

  _lobeAt(clientX, clientY) {
    // Approximate: based on screen quadrant. Not used heavily — main.js can pass null.
    return null;
  }

  // ---------- public effects ----------

  setSearchHighlight(idsOrNull) {
    this.searchHighlight = idsOrNull ? new Set(idsOrNull) : null;
    // Apply dim by tweaking per-instance colors
    for (const [type, grp] of Object.entries(this.nodesByType)) {
      const mesh = grp.mesh;
      const baseColor = new THREE.Color(NODE_COLORS[type] || 0xffffff);
      const arr = mesh.instanceColor.array;
      grp.ids.forEach((id, i) => {
        let c = baseColor.clone();
        if (this.searchHighlight && !this.searchHighlight.has(id)) {
          c.multiplyScalar(0.15);
        }
        arr[i * 3] = c.r; arr[i * 3 + 1] = c.g; arr[i * 3 + 2] = c.b;
      });
      mesh.instanceColor.needsUpdate = true;
    }
  }

  focusLobe(lobeName) {
    this.focusedLobe = lobeName;
    this.targetZoom = lobeName ? 4.2 : 7;
  }

  resetView() {
    this.focusedLobe = null;
    this.targetZoom = 7;
    this.targetRot.x = 0;
    this.targetRot.y = 0;
    this.autoRotate = true;
  }

  // ---------- loop ----------

  _onResize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _tick() {
    if (this.autoRotate) this.targetRot.y += 0.0035;
    this.rot.x += (this.targetRot.x - this.rot.x) * 0.08;
    this.rot.y += (this.targetRot.y - this.rot.y) * 0.08;
    this.zoom += (this.targetZoom - this.zoom) * 0.1;
    this.brainGroup.rotation.x = this.rot.x;
    this.brainGroup.rotation.y = this.rot.y;
    this.camera.position.z = this.zoom;

    // Pulse fresh nodes
    const t = performance.now() * 0.001;
    const dummy = new THREE.Object3D();
    for (const [type, grp] of Object.entries(this.nodesByType)) {
      let dirty = false;
      grp.ids.forEach((id, i) => {
        const info = this.idIndex.get(id);
        if (!info || !info.fresh) return;
        const p = info.pos;
        const pulse = 1.0 + 0.25 * Math.sin(t * 2.5 + i);
        const base = 0.6 + 5 * 0.1;
        dummy.position.set(p.x, p.y, p.z);
        dummy.scale.setScalar(base * 1.6 * pulse);
        dummy.updateMatrix();
        grp.mesh.setMatrixAt(i, dummy.matrix);
        dirty = true;
      });
      if (dirty) grp.mesh.instanceMatrix.needsUpdate = true;
    }

    // Apply node positions inside rotated brain group
    for (const grp of Object.values(this.nodesByType)) {
      grp.mesh.rotation.x = this.rot.x;
      grp.mesh.rotation.y = this.rot.y;
    }
    if (this.edgeLines) {
      this.edgeLines.rotation.x = this.rot.x;
      this.edgeLines.rotation.y = this.rot.y;
    }

    this.renderer.render(this.scene, this.camera);
    requestAnimationFrame(this._tick);
  }

  dispose() {
    window.removeEventListener("resize", this._onResize);
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }
  }
}
