"""Seed three demo nodes into an empty graph so the first-run UI isn't blank.

Seeded nodes are ordinary nodes — they can be edited, soft-deleted, or
restored through the normal UI/API. Seed only runs when the graph is
totally empty (including soft-deleted nodes). Set SEED_DEMO_NODES=0 in
the environment to skip seeding (used by the test suite).
"""
from __future__ import annotations

import os

from brain.graph import BrainGraph


DEMO_NODES: list[dict] = [
    {
        "type": "idea",
        "title": "Попробовать чехол на воздушный фильтр мотоцикла",
        "importance": 7,
        "required_time_minutes": 45,
        "required_money": 0,
        "energy": "medium",
        "tags": ["мотоцикл", "эксперимент"],
        "status": "active",
    },
    {
        "type": "task",
        "title": "Подготовить отчёт по объекту №4",
        "importance": 9,
        "required_time_minutes": 90,
        "required_money": 0,
        "energy": "high",
        "tags": ["работа"],
        "status": "active",
    },
    {
        "type": "idea",
        "title": "Второй мозг — приложение против хаоса в голове",
        "importance": 10,
        "required_time_minutes": 0,
        "required_money": 0,
        "energy": "low",
        "tags": ["идеи", "проект"],
        "status": "active",
    },
]


def is_empty(graph: BrainGraph) -> bool:
    return graph._g.number_of_nodes() == 0


def seed_demo_nodes(graph: BrainGraph) -> list[str]:
    """Add demo nodes if and only if the graph is empty. Returns the new ids."""
    if os.environ.get("SEED_DEMO_NODES", "1") == "0":
        return []
    if not is_empty(graph):
        return []
    ids: list[str] = []
    for n in DEMO_NODES:
        fields = dict(n)
        node_type = fields.pop("type")
        ids.append(graph.add_node(node_type, **fields))
    graph.save()
    return ids
