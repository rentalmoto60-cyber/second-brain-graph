"""In-memory knowledge graph with CRUD, undo, audit log and actionable query."""
from __future__ import annotations

import copy
import math
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import networkx as nx

from brain.config import (
    ENERGY_PENALTIES,
    FITS_TIME_BOOST,
    PRIORITY_WEIGHTS,
    UNDO_STACK_LIMIT,
    URGENCY_SCALE,
)
from brain.models import (
    IMMUTABLE_NODE_FIELDS,
    TASK_DEFAULTS,
    EdgeType,
    NodeType,
    Status,
    validate_task_payload,
)
from brain.storage import Storage


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_enum(value: Any, enum_cls) -> str:
    if isinstance(value, enum_cls):
        return value.value
    if isinstance(value, str) and value in {m.value for m in enum_cls}:
        return value
    raise ValueError(f"expected {enum_cls.__name__}, got {value!r}")


class BrainGraph:
    def __init__(self, storage: Storage):
        self._storage = storage
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()
        self._audit_log: list[dict] = []
        self._undo_stack: deque[dict] = deque(maxlen=UNDO_STACK_LIMIT)

    # ---------- persistence ----------

    @classmethod
    def load(cls, storage: Storage) -> "BrainGraph":
        graph = cls(storage)
        data = storage.load_graph()
        for node in data.get("nodes", []):
            graph._g.add_node(node["id"], **node)
        for edge in data.get("edges", []):
            graph._g.add_edge(
                edge["from"],
                edge["to"],
                key=edge["type"],
                type=edge["type"],
            )
        graph._audit_log = list(data.get("audit_log", []))
        return graph

    def save(self) -> None:
        nodes = [dict(self._g.nodes[n]) for n in self._g.nodes]
        edges = [
            {"from": u, "to": v, "type": k}
            for u, v, k in self._g.edges(keys=True)
        ]
        self._storage.save_graph(
            {"nodes": nodes, "edges": edges, "audit_log": self._audit_log}
        )

    # ---------- internal helpers ----------

    def _log(self, entry: dict) -> None:
        entry = {"timestamp": _now_iso(), **entry}
        self._audit_log.append(entry)

    def _push_undo(self, action: dict) -> None:
        self._undo_stack.append(action)

    def _require_node(self, node_id: str) -> dict:
        if node_id not in self._g.nodes:
            raise ValueError(f"node {node_id} not found")
        return self._g.nodes[node_id]

    def _would_create_blocks_cycle(self, from_id: str, to_id: str) -> bool:
        if from_id == to_id:
            return True
        blocks_view = nx.DiGraph()
        for u, v, k in self._g.edges(keys=True):
            if k == EdgeType.BLOCKS.value:
                blocks_view.add_edge(u, v)
        if to_id not in blocks_view or from_id not in blocks_view:
            return False
        return nx.has_path(blocks_view, to_id, from_id)

    # ---------- node CRUD ----------

    def add_node(self, node_type: NodeType | str, **fields) -> str:
        type_value = _coerce_enum(node_type, NodeType)

        node = dict(TASK_DEFAULTS)
        node.update(fields)
        if "title" not in node:
            raise ValueError("title is required")

        if "status" in node and isinstance(node["status"], Status):
            node["status"] = node["status"].value

        validate_task_payload(node)

        node_id = fields.get("id") or str(uuid.uuid4())
        now = _now_iso()
        node["id"] = node_id
        node["type"] = type_value
        node["created_at"] = node.get("created_at") or now
        node["updated_at"] = now

        if node_id in self._g.nodes:
            raise ValueError(f"node {node_id} already exists")

        self._g.add_node(node_id, **node)

        self._log({
            "action": "add_node",
            "node_id": node_id,
            "before": None,
            "after": copy.deepcopy(node),
        })
        self._push_undo({"kind": "add_node", "node_id": node_id})
        return node_id

    def get_node(self, node_id: str) -> dict:
        data = self._require_node(node_id)
        return copy.deepcopy(dict(data))

    def update_node(self, node_id: str, **fields) -> None:
        current = self._require_node(node_id)

        for forbidden in IMMUTABLE_NODE_FIELDS:
            if forbidden in fields:
                raise ValueError(f"field '{forbidden}' is immutable")

        new_state = dict(current)
        new_state.update(fields)
        if "status" in new_state and isinstance(new_state["status"], Status):
            new_state["status"] = new_state["status"].value

        validate_task_payload(new_state)
        new_state["updated_at"] = _now_iso()

        before = copy.deepcopy(dict(current))
        self._g.nodes[node_id].clear()
        self._g.nodes[node_id].update(new_state)

        self._log({
            "action": "update_node",
            "node_id": node_id,
            "before": before,
            "after": copy.deepcopy(new_state),
        })
        self._push_undo({"kind": "update_node", "node_id": node_id, "before": before})

    def soft_delete(self, node_id: str) -> None:
        current = self._require_node(node_id)
        before = copy.deepcopy(dict(current))
        new_state = dict(current)
        new_state["status"] = Status.DELETED.value
        new_state["updated_at"] = _now_iso()

        self._g.nodes[node_id].clear()
        self._g.nodes[node_id].update(new_state)

        self._log({
            "action": "soft_delete",
            "node_id": node_id,
            "before": before,
            "after": copy.deepcopy(new_state),
        })
        self._push_undo({"kind": "soft_delete", "node_id": node_id, "before": before})

    def restore(self, node_id: str) -> None:
        current = self._require_node(node_id)
        before = copy.deepcopy(dict(current))
        new_state = dict(current)
        new_state["status"] = Status.ACTIVE.value
        new_state["updated_at"] = _now_iso()

        self._g.nodes[node_id].clear()
        self._g.nodes[node_id].update(new_state)

        self._log({
            "action": "restore",
            "node_id": node_id,
            "before": before,
            "after": copy.deepcopy(new_state),
        })
        self._push_undo({"kind": "restore", "node_id": node_id, "before": before})

    # ---------- edge CRUD ----------

    def add_edge(self, from_id: str, to_id: str, edge_type: EdgeType | str) -> None:
        self._require_node(from_id)
        self._require_node(to_id)
        type_value = _coerce_enum(edge_type, EdgeType)

        if self._g.has_edge(from_id, to_id, key=type_value):
            raise ValueError(f"edge {from_id}->{to_id} ({type_value}) already exists")

        if type_value == EdgeType.BLOCKS.value:
            if self._would_create_blocks_cycle(from_id, to_id):
                raise ValueError("BLOCKS edge would create a cycle")

        self._g.add_edge(from_id, to_id, key=type_value, type=type_value)

        self._log({
            "action": "add_edge",
            "edge": {"from": from_id, "to": to_id, "type": type_value},
            "before": None,
            "after": {"from": from_id, "to": to_id, "type": type_value},
        })
        self._push_undo({
            "kind": "add_edge",
            "from": from_id, "to": to_id, "type": type_value,
        })

    def remove_edge(self, from_id: str, to_id: str, edge_type: EdgeType | str) -> None:
        type_value = _coerce_enum(edge_type, EdgeType)
        if not self._g.has_edge(from_id, to_id, key=type_value):
            raise ValueError(f"edge {from_id}->{to_id} ({type_value}) not found")
        self._g.remove_edge(from_id, to_id, key=type_value)

        self._log({
            "action": "remove_edge",
            "edge": {"from": from_id, "to": to_id, "type": type_value},
            "before": {"from": from_id, "to": to_id, "type": type_value},
            "after": None,
        })
        self._push_undo({
            "kind": "remove_edge",
            "from": from_id, "to": to_id, "type": type_value,
        })

    # ---------- undo ----------

    def undo_last_action(self) -> None:
        if not self._undo_stack:
            raise ValueError("undo stack is empty")
        action = self._undo_stack.pop()
        kind = action["kind"]

        if kind == "add_node":
            node_id = action["node_id"]
            before = copy.deepcopy(dict(self._g.nodes[node_id])) if node_id in self._g.nodes else None
            if node_id in self._g.nodes:
                self._g.remove_node(node_id)
            self._log({
                "action": "undo_add_node",
                "node_id": node_id,
                "before": before,
                "after": None,
            })

        elif kind in {"update_node", "soft_delete", "restore"}:
            node_id = action["node_id"]
            before_state = action["before"]
            current = copy.deepcopy(dict(self._g.nodes[node_id])) if node_id in self._g.nodes else None
            self._g.nodes[node_id].clear()
            self._g.nodes[node_id].update(before_state)
            self._log({
                "action": f"undo_{kind}",
                "node_id": node_id,
                "before": current,
                "after": copy.deepcopy(before_state),
            })

        elif kind == "add_edge":
            self._g.remove_edge(action["from"], action["to"], key=action["type"])
            self._log({
                "action": "undo_add_edge",
                "edge": {"from": action["from"], "to": action["to"], "type": action["type"]},
                "before": {"from": action["from"], "to": action["to"], "type": action["type"]},
                "after": None,
            })

        elif kind == "remove_edge":
            self._g.add_edge(
                action["from"], action["to"],
                key=action["type"], type=action["type"],
            )
            self._log({
                "action": "undo_remove_edge",
                "edge": {"from": action["from"], "to": action["to"], "type": action["type"]},
                "before": None,
                "after": {"from": action["from"], "to": action["to"], "type": action["type"]},
            })
        else:
            raise ValueError(f"unknown undo kind: {kind}")

    # ---------- audit ----------

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        if limit <= 0:
            return []
        return copy.deepcopy(self._audit_log[-limit:])

    # ---------- actionable ----------

    def get_actionable(
        self,
        free_time_minutes: int | None = None,
        strict_time_filter: bool = False,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        results: list[dict] = []

        for node_id in self._g.nodes:
            data = self._g.nodes[node_id]
            if data.get("status") != Status.ACTIVE.value:
                continue
            if self._is_blocked(node_id):
                continue

            required = int(data.get("required_time_minutes") or 0)
            fits = (free_time_minutes is None) or (required <= free_time_minutes)

            if strict_time_filter and free_time_minutes is not None and not fits:
                continue

            priority = self._compute_priority(data, now)
            if fits and free_time_minutes is not None and not strict_time_filter:
                priority *= FITS_TIME_BOOST

            out = copy.deepcopy(dict(data))
            out["_computed_priority"] = priority
            results.append(out)

        results.sort(key=lambda x: x["_computed_priority"], reverse=True)
        return results

    def _is_blocked(self, node_id: str) -> bool:
        for u, _v, k in self._g.in_edges(node_id, keys=True):
            if k != EdgeType.BLOCKS.value:
                continue
            blocker_status = self._g.nodes[u].get("status")
            if blocker_status != Status.DONE.value:
                return True
        return False

    def _compute_priority(self, node: dict, now: datetime) -> float:
        w = PRIORITY_WEIGHTS
        importance = float(node.get("importance") or 0)
        required_time = max(int(node.get("required_time_minutes") or 0), 1)
        urgency = self._urgency_score(node.get("deadline"), now)
        energy = node.get("energy")
        energy_pen = ENERGY_PENALTIES.get(energy, 0)

        return (
            w["importance"] * importance
            + w["urgency"] * urgency
            + w["time"] * (1.0 / required_time)
            - w["energy"] * energy_pen
            + w["unlock"] * 0
            - w["unfunded"] * 0
        )

    @staticmethod
    def _urgency_score(deadline: Any, now: datetime) -> float:
        if not deadline:
            return 0.0
        try:
            dt = datetime.fromisoformat(deadline)
        except (ValueError, TypeError):
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days_left = (dt - now).total_seconds() / 86400.0
        return math.exp(-days_left / URGENCY_SCALE)
