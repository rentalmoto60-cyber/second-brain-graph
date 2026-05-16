"""Export the BrainGraph for the frontend and compute 3D node positions."""
from __future__ import annotations

import hashlib
import math
from typing import Any

from brain.config import LOBE_CENTERS, LOBE_SPREAD, TAG_TO_LOBE
from brain.graph import BrainGraph


def _seeded_rng(seed_str: str) -> "list[float]":
    """Deterministic pseudo-random sequence in [0, 1) derived from a string."""
    digest = hashlib.sha256(seed_str.encode("utf-8")).digest()
    return [b / 255.0 for b in digest]


def _gaussian_pair(u1: float, u2: float) -> tuple[float, float]:
    """Box-Muller transform: two uniforms in (0,1) → two N(0,1) samples."""
    u1 = max(u1, 1e-9)
    r = math.sqrt(-2.0 * math.log(u1))
    theta = 2.0 * math.pi * u2
    return r * math.cos(theta), r * math.sin(theta)


def _pick_lobe_for_tags(tags: list[str]) -> str:
    for tag in tags or []:
        if tag in TAG_TO_LOBE:
            return TAG_TO_LOBE[tag]
    return TAG_TO_LOBE["_default"]


def _pick_hemisphere(rng: list[float], lobe: str) -> str:
    centers = LOBE_CENTERS[lobe]
    if "center" in centers:
        return "center"
    return "left" if rng[0] < 0.5 else "right"


def compute_3d_positions(graph: BrainGraph) -> dict[str, tuple[float, float, float]]:
    """Return {node_id: (x, y, z)} deterministic positions inside the brain."""
    positions: dict[str, tuple[float, float, float]] = {}
    for node_id, data in graph._g.nodes(data=True):
        tags = data.get("tags") or []
        lobe = _pick_lobe_for_tags(tags)
        rng = _seeded_rng(node_id)
        hemi = _pick_hemisphere(rng, lobe)
        cx, cy, cz = LOBE_CENTERS[lobe][hemi]

        dx, dy = _gaussian_pair(rng[2], rng[3])
        dz, _  = _gaussian_pair(rng[4], rng[5])
        positions[node_id] = (
            cx + dx * LOBE_SPREAD,
            cy + dy * LOBE_SPREAD,
            cz + dz * LOBE_SPREAD,
        )
    return positions


def export_graph(graph: BrainGraph) -> dict[str, Any]:
    """Snapshot of the graph for the frontend (nodes + edges + 3D positions)."""
    positions = compute_3d_positions(graph)
    nodes = []
    for node_id, data in graph._g.nodes(data=True):
        x, y, z = positions[node_id]
        node = dict(data)
        node["position"] = {"x": x, "y": y, "z": z}
        nodes.append(node)
    edges = [
        {"from": u, "to": v, "type": k}
        for u, v, k in graph._g.edges(keys=True)
    ]
    return {"nodes": nodes, "edges": edges}
