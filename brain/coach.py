"""GTD coach: snapshot the graph and ask Gemini for 3 Socratic questions.

Read-only with respect to the graph — never mutates state.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from google import genai

from brain.config import GEMINI_MODEL
from brain.graph import BrainGraph


DASHBOARD_LIMIT = 10
RECENT_DONE_DAYS = 7


SYSTEM_PROMPT = """Ты — GTD-коуч. Тебе показывают состояние «второго мозга» пользователя. Твоя задача — задать ровно 3 коротких сократических вопроса, которые помогут ему понять что делать прямо сейчас.

Правила:
- Не давай советов. Только вопросы.
- Вопросы должны быть конкретные, со ссылками на узлы из графа (по их названиям).
- Первый вопрос — про энергию и состояние сейчас.
- Второй вопрос — про самую важную/срочную задачу.
- Третий вопрос — про то что блокирует действие.

Верни ТОЛЬКО JSON со структурой {"questions": ["...", "...", "..."]} (ровно 3 строки), без markdown."""


DEFAULT_QUESTIONS = [
    "Сколько у тебя сейчас энергии — низкая, средняя, высокая?",
    "Какая задача из списка ощущается самой важной прямо сейчас?",
    "Что мешает начать прямо сейчас — нет ясности, времени или энергии?",
]


def _summarize_node(n: dict) -> dict:
    return {
        "id": n.get("id"),
        "title": n.get("title"),
        "type": n.get("type"),
        "status": n.get("status"),
        "importance": n.get("importance"),
        "energy": n.get("energy"),
        "time_min": n.get("required_time_minutes"),
        "deadline": n.get("deadline"),
        "tags": n.get("tags") or [],
    }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def export_dashboard(graph: BrainGraph, *, now: datetime | None = None) -> dict:
    """Snapshot the graph for the coach: counts, actionable, inbox, recent done."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RECENT_DONE_DAYS)

    all_nodes = [d for _, d in graph._g.nodes(data=True)]
    active_nodes = [d for d in all_nodes if d.get("status") != "deleted"]

    by_type = Counter(d.get("type", "?") for d in active_nodes)
    by_status = Counter(d.get("status", "?") for d in active_nodes)

    actionable = graph.get_actionable()[:DASHBOARD_LIMIT]

    inbox_nodes = sorted(
        (d for d in active_nodes if d.get("status") == "inbox"),
        key=lambda d: d.get("created_at") or "",
        reverse=True,
    )[:DASHBOARD_LIMIT]

    recent_done: list[dict] = []
    for entry in graph._audit_log:
        if entry.get("action") != "update_node":
            continue
        before = entry.get("before") or {}
        after = entry.get("after") or {}
        if after.get("status") != "done" or before.get("status") == "done":
            continue
        ts = _parse_ts(entry.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        recent_done.append({
            "id": entry.get("node_id"),
            "title": after.get("title", ""),
            "completed_at": entry.get("timestamp"),
        })
    recent_done.sort(key=lambda x: x["completed_at"], reverse=True)
    recent_done = recent_done[:DASHBOARD_LIMIT * 2]

    return {
        "now": now.isoformat(),
        "total_active": len(active_nodes),
        "by_type": dict(by_type),
        "by_status": dict(by_status),
        "actionable": [_summarize_node(n) for n in actionable],
        "inbox": [_summarize_node(n) for n in inbox_nodes],
        "recent_done": recent_done,
        "recent_done_count": len(recent_done),
    }


def _make_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get one at https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)


def get_questions(
    graph: BrainGraph, *, client: genai.Client | None = None
) -> dict[str, Any]:
    """Ask Gemini for 3 Socratic questions about the current dashboard.

    Returns {"questions": [str, str, str], "dashboard": {...}}.
    """
    dashboard = export_dashboard(graph)
    payload = json.dumps(dashboard, ensure_ascii=False, sort_keys=True)

    client = client or _make_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{SYSTEM_PROMPT}\n\nДашборд:\n{payload}",
        config={"response_mime_type": "application/json"},
    )
    parsed = json.loads(response.text)
    questions = parsed.get("questions") or []
    # Pad with defaults / trim to exactly 3 if Gemini misbehaves.
    questions = (list(questions) + DEFAULT_QUESTIONS)[:3]
    return {"questions": questions, "dashboard": dashboard}
