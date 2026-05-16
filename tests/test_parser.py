import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from brain.parser import parse_thought, parsed_to_node_fields


def _fake_response(payload: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))]
    )


def _fake_client(payload: dict):
    client = MagicMock()
    client.messages.create.return_value = _fake_response(payload)
    return client


def test_parse_thought_passes_text_and_returns_dict():
    payload = {
        "type": "task", "title": "Сделать зарядку",
        "importance": 6, "required_time_minutes": 15, "required_money": 0,
        "energy": "high", "deadline": None, "tags": ["спорт"],
        "context": None, "confidence": 0.92, "needs_clarification": False,
        "raw_text": "надо сделать зарядку",
    }
    client = _fake_client(payload)
    result = parse_thought("надо сделать зарядку", client=client)
    assert result == payload

    args = client.messages.create.call_args.kwargs
    assert args["model"].startswith("claude-")
    assert args["messages"][0]["content"] == "надо сделать зарядку"
    sys = args["system"][0]
    assert sys["cache_control"] == {"type": "ephemeral"}
    assert "ТОЛЬКО валидный JSON" in sys["text"] or "ТОЛЬКО" in sys["text"]
    fmt = args["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert "confidence" in fmt["schema"]["properties"]


def test_parse_thought_rejects_empty():
    with pytest.raises(ValueError):
        parse_thought("   ", client=_fake_client({}))


def test_high_confidence_goes_active():
    parsed = {
        "type": "task", "title": "Купить хлеб", "importance": 5,
        "required_time_minutes": 30, "required_money": 0, "energy": "low",
        "deadline": None, "tags": [], "context": None,
        "confidence": 0.95, "needs_clarification": False, "raw_text": "купить хлеб",
    }
    node_type, fields = parsed_to_node_fields(parsed)
    assert node_type == "task"
    assert fields["status"] == "active"
    assert fields["title"] == "Купить хлеб"
    assert fields["importance"] == 5
    assert fields["energy"] == "low"


def test_low_confidence_goes_inbox_with_echo():
    parsed = {
        "type": "task", "title": "что-то про мотоцикл", "importance": 5,
        "required_time_minutes": 30, "required_money": 0, "energy": None,
        "deadline": None, "tags": ["мотоцикл"], "context": None,
        "confidence": 0.4, "needs_clarification": False,
        "raw_text": "ну там с мотоциклом надо это самое",
    }
    _, fields = parsed_to_node_fields(parsed)
    assert fields["status"] == "inbox"
    assert "Требует уточнения" in fields["context"]
    assert "мотоцикл" in fields["context"]


def test_needs_clarification_flag_forces_inbox():
    parsed = {
        "type": "task", "title": "X", "importance": 5,
        "required_time_minutes": 30, "required_money": 0, "energy": None,
        "deadline": None, "tags": [], "context": None,
        "confidence": 0.99, "needs_clarification": True, "raw_text": "X",
    }
    _, fields = parsed_to_node_fields(parsed)
    assert fields["status"] == "inbox"


def test_project_type_propagates():
    parsed = {
        "type": "project", "title": "Запустить блог", "importance": 8,
        "required_time_minutes": 600, "required_money": 0, "energy": "medium",
        "deadline": None, "tags": ["проект"], "context": None,
        "confidence": 0.9, "needs_clarification": False,
        "raw_text": "хочу запустить блог",
    }
    node_type, fields = parsed_to_node_fields(parsed)
    assert node_type == "project"
    assert fields["status"] == "active"
