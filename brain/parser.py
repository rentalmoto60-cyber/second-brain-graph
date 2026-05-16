"""Claude API parser: free-form Russian thought → structured node JSON."""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic


PARSER_MODEL = os.environ.get("PARSER_MODEL", "claude-sonnet-4-6")
PARSER_MAX_TOKENS = 1024
PARSER_TIMEOUT_SECONDS = 30.0


SYSTEM_PROMPT = """Ты — парсер мыслей для системы «Второй мозг». Тебе дают сырой текст, надиктованный пользователем по-русски. Твоя задача — вернуть строго JSON со структурой узла.

Поля:
- type: "task" | "idea" | "project". По умолчанию task. Если пользователь сказал «идея» или «было бы круто» — idea. Если описан большой замысел из нескольких подзадач — project.
- title: короткое название, до 80 символов, в повелительном наклонении для task («Поставить чехол на воздушный фильтр»). Для idea — назывное («Идея: ...»). Не дублируй полностью сырой текст.
- importance: целое 1-10. По умолчанию 5. Повышай если в речи слышна срочность, важность, эмоция.
- required_time_minutes: целое, оценка времени в минутах. По умолчанию 30. Если непонятно — оставь 30.
- required_money: число, 0 если не упоминается.
- energy: "low" | "medium" | "high" | null. Эвристика: «позвонить», «написать» — low; «разобраться с» — medium; «сделать», «починить», «купить» физически — high.
- deadline: ISO 8601 строка ("2026-05-20T18:00:00") или null. Извлекай только если в речи явно сказана дата/время.
- tags: массив коротких строк (1-3 элемента). Извлекай по контексту: мотоцикл → ["мотоцикл"], работа → ["работа"], спорт → ["спорт"]. Пустой массив, если не понимаешь.
- context: строка с уточнениями (свободная форма) или null.
- confidence: число 0.0-1.0. Твоя уверенность что распарсил правильно. Если речь обрывочная, бессвязная или ты гадаешь — ставь меньше 0.7.
- needs_clarification: bool. True если confidence < 0.7 ИЛИ если упущена важная деталь (непонятно про что вообще речь).
- raw_text: исходный текст без изменений.

Верни ТОЛЬКО валидный JSON, без markdown-обёрток, без пояснений."""


PARSED_THOUGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["task", "idea", "project"]},
        "title": {"type": "string"},
        "importance": {"type": "integer", "enum": list(range(1, 11))},
        "required_time_minutes": {"type": "integer"},
        "required_money": {"type": "number"},
        "energy": {"anyOf": [{"type": "string", "enum": ["low", "medium", "high"]}, {"type": "null"}]},
        "deadline": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "context": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "confidence": {"type": "number"},
        "needs_clarification": {"type": "boolean"},
        "raw_text": {"type": "string"},
    },
    "required": [
        "type", "title", "importance", "required_time_minutes", "required_money",
        "energy", "deadline", "tags", "context", "confidence",
        "needs_clarification", "raw_text",
    ],
    "additionalProperties": False,
}


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(timeout=PARSER_TIMEOUT_SECONDS)


def parse_thought(text: str, *, client: anthropic.Anthropic | None = None) -> dict[str, Any]:
    """Run a single Claude call and return the parsed-thought JSON dict.

    Raises:
        ValueError if `text` is empty.
        anthropic.APIError on API failures.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("text must be a non-empty string")

    client = client or _make_client()
    response = client.messages.create(
        model=PARSER_MODEL,
        max_tokens=PARSER_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": text}],
        output_config={
            "format": {"type": "json_schema", "schema": PARSED_THOUGHT_SCHEMA}
        },
    )
    raw = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(raw)


def parsed_to_node_fields(parsed: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Translate parser JSON to (node_type, fields) for BrainGraph.add_node.

    Applies the confidence rule: confidence < 0.7 OR needs_clarification → inbox
    with the original parse echoed into context for manual review.
    """
    needs_review = (
        bool(parsed.get("needs_clarification"))
        or float(parsed.get("confidence", 0)) < 0.7
    )
    if needs_review:
        status = "inbox"
        context = (
            "Требует уточнения. Распарсено как: "
            + json.dumps(parsed, ensure_ascii=False)
        )
    else:
        status = "active"
        context = parsed.get("context")

    fields = {
        "title": parsed["title"],
        "status": status,
        "importance": int(parsed["importance"]),
        "required_time_minutes": int(parsed["required_time_minutes"]),
        "required_money": float(parsed["required_money"]),
        "energy": parsed.get("energy"),
        "deadline": parsed.get("deadline"),
        "tags": list(parsed.get("tags") or []),
        "context": context,
    }
    return parsed["type"], fields
