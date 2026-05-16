"""GTD coach: snapshot the graph and ask Claude for 3 Socratic questions.

Read-only with respect to the graph — never mutates state.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic

from brain.graph import BrainGraph


COACH_MODEL = os.environ.get("COACH_MODEL", "claude-sonnet-4-6")
COACH_MAX_TOKENS = 1024
COACH_TIMEOUT_SECONDS = 30.0
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


QUESTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


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


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(timeout=COACH_TIMEOUT_SECONDS)


def get_questions(
    graph: BrainGraph, *, client: anthropic.Anthropic | None = None
) -> dict[str, Any]:
    """Ask Claude for 3 Socratic questions about the current dashboard.

    Returns {"questions": [str, str, str], "dashboard": {...}}.
    """
    dashboard = export_dashboard(graph)
    payload = json.dumps(dashboard, ensure_ascii=False, sort_keys=True)

    client = client or _make_client()
    response = client.messages.create(
        model=COACH_MODEL,
        max_tokens=COACH_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": payload}],
        output_config={
            "format": {"type": "json_schema", "schema": QUESTIONS_SCHEMA}
        },
    )
    raw = next((b.text for b in response.content if b.type == "text"), "")
    parsed = json.loads(raw)
    questions = parsed.get("questions") or []
    if len(questions) != 3:
        # Coerce: pad with neutral asks or trim to 3.
        defaults = [
            "Сколько у тебя сейчас энергии — низкая, средняя, высокая?",
            "Какая задача из списка ощущается самой важной прямо сейчас?",
            "Что мешает начать прямо сейчас — нет ясности, времени или энергии?",
        ]
        questions = (list(questions) + defaults)[:3]
    return {"questions": questions, "dashboard": dashboard}
