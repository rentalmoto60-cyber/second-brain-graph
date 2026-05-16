# second-brain-graph

Personal knowledge graph for tasks, ideas and (later) finances.
Phase 1.1: deterministic core — CRUD, undo, audit log, `get_actionable()`.

## Install

```
pip install -r requirements.txt
```

## Run tests

```
python3 -m pytest
```

## Example

```python
from brain import BrainGraph, NodeType, EdgeType, Storage

g = BrainGraph(Storage("brain.json"))

write = g.add_node(NodeType.TASK, title="write report",
                   status="active", importance=8,
                   required_time_minutes=45, energy="medium")
ship  = g.add_node(NodeType.TASK, title="ship report",
                   status="active", importance=9,
                   required_time_minutes=10)

g.add_edge(write, ship, EdgeType.BLOCKS)  # ship is blocked until write is done

for task in g.get_actionable(free_time_minutes=30):
    print(task["title"], task["_computed_priority"])

g.save()
```
