"""JSON-file storage for the brain graph. Atomic writes, human-readable."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any


EMPTY_STATE: dict[str, list] = {"nodes": [], "edges": [], "audit_log": []}


class Storage:
    def __init__(self, path: str = "brain.json"):
        self.path = path

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def load_graph(self) -> dict[str, Any]:
        if not self.exists():
            return {"nodes": [], "edges": [], "audit_log": []}
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("nodes", [])
        data.setdefault("edges", [])
        data.setdefault("audit_log", [])
        return data

    def save_graph(self, data: dict[str, Any]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".brain-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
