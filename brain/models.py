"""Node/edge types, statuses and payload validation."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    TASK = "task"
    PROJECT = "project"
    IDEA = "idea"
    FINANCE_EVENT = "finance_event"
    CALENDAR_BLOCK = "calendar_block"


class Status(str, Enum):
    INBOX = "inbox"
    ACTIVE = "active"
    DONE = "done"
    WAITING = "waiting"
    DELETED = "deleted"


class EdgeType(str, Enum):
    BLOCKS = "BLOCKS"
    FUNDED_BY = "FUNDED_BY"
    PART_OF = "PART_OF"
    CONTEXT_LINK = "CONTEXT_LINK"


VALID_ENERGY = {"low", "medium", "high", None}


def _is_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_task_payload(payload: dict) -> None:
    """Validate fields of a task-like node. Raises ValueError on invalid input.

    Only checks fields that are present; required-field enforcement is the
    caller's responsibility (BrainGraph.add_node fills defaults first).
    """
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")

    if "status" in payload:
        status = payload["status"]
        if isinstance(status, Status):
            pass
        elif isinstance(status, str) and status in {s.value for s in Status}:
            pass
        else:
            raise ValueError(f"status must be one of {[s.value for s in Status]}")

    if "required_time_minutes" in payload:
        v = payload["required_time_minutes"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ValueError("required_time_minutes must be a non-negative int")

    if "required_money" in payload:
        v = payload["required_money"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise ValueError("required_money must be a non-negative number")

    if "importance" in payload:
        v = payload["importance"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 10:
            raise ValueError("importance must be an int in [1, 10]")

    if "energy" in payload:
        v = payload["energy"]
        if v not in VALID_ENERGY:
            raise ValueError(f"energy must be one of {sorted(x for x in VALID_ENERGY if x)} or None")

    if "context" in payload and payload["context"] is not None:
        if not isinstance(payload["context"], str):
            raise ValueError("context must be a string or None")

    if "deadline" in payload and payload["deadline"] is not None:
        if not _is_iso_datetime(payload["deadline"]):
            raise ValueError("deadline must be an ISO 8601 datetime string or None")

    if "tags" in payload and payload["tags"] is not None:
        tags = payload["tags"]
        if not isinstance(tags, list) or not all(
            isinstance(t, str) and t.strip() for t in tags
        ):
            raise ValueError("tags must be a list of non-empty strings")


TASK_DEFAULTS = {
    "status": Status.INBOX.value,
    "required_time_minutes": 0,
    "required_money": 0.0,
    "importance": 5,
    "energy": None,
    "context": None,
    "deadline": None,
    "tags": [],
}

IMMUTABLE_NODE_FIELDS = {"id", "created_at", "type"}
