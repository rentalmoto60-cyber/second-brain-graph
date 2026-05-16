import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from brain.coach import (
    DASHBOARD_LIMIT,
    RECENT_DONE_DAYS,
    SYSTEM_PROMPT,
    export_dashboard,
    get_questions,
)
from brain.graph import BrainGraph
from brain.models import NodeType, Status
from brain.storage import Storage


@pytest.fixture
def graph(tmp_path):
    return BrainGraph(Storage(str(tmp_path / "brain.json")))


# ---------- dashboard ----------

def test_dashboard_shape_on_empty_graph(graph):
    d = export_dashboard(graph)
    assert d["total_active"] == 0
    assert d["by_type"] == {}
    assert d["by_status"] == {}
    assert d["actionable"] == []
    assert d["inbox"] == []
    assert d["recent_done"] == []
    assert "now" in d


def test_dashboard_counts_by_type_and_status(graph):
    graph.add_node(NodeType.TASK, title="a", status="active")
    graph.add_node(NodeType.TASK, title="b", status="inbox")
    graph.add_node(NodeType.IDEA, title="c", status="active")
    deleted = graph.add_node(NodeType.TASK, title="gone")
    graph.soft_delete(deleted)

    d = export_dashboard(graph)
    assert d["total_active"] == 3
    assert d["by_type"]["task"] == 2
    assert d["by_type"]["idea"] == 1
    assert d["by_status"]["active"] == 2
    assert d["by_status"]["inbox"] == 1
    # deleted node excluded
    assert "deleted" not in d["by_status"]


def test_dashboard_actionable_capped_and_summarized(graph):
    for i in range(15):
        graph.add_node(NodeType.TASK, title=f"task {i}", status="active", importance=i % 10 + 1)

    d = export_dashboard(graph)
    assert len(d["actionable"]) == DASHBOARD_LIMIT
    for n in d["actionable"]:
        # summary fields only — no audit log / context leak
        assert set(n.keys()) >= {"id", "title", "type", "importance"}


def test_dashboard_inbox_capped_and_newest_first(graph):
    ids = [
        graph.add_node(NodeType.TASK, title=f"thought {i}", status="inbox")
        for i in range(12)
    ]
    d = export_dashboard(graph)
    assert len(d["inbox"]) == DASHBOARD_LIMIT
    # most recently created should be first
    assert d["inbox"][0]["id"] == ids[-1]


def test_dashboard_recent_done_filters_by_time_window(graph, monkeypatch):
    a = graph.add_node(NodeType.TASK, title="recent", status="active")
    b = graph.add_node(NodeType.TASK, title="old", status="active")

    # Mark `a` done now
    graph.update_node(a, status="done")
    # Mark `b` done, then rewrite the audit timestamp to be 30d ago
    graph.update_node(b, status="done")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for entry in graph._audit_log:
        if entry.get("node_id") == b and entry.get("action") == "update_node":
            entry["timestamp"] = old

    d = export_dashboard(graph)
    titles = [n["title"] for n in d["recent_done"]]
    assert "recent" in titles
    assert "old" not in titles


def test_dashboard_recent_done_ignores_non_done_updates(graph):
    nid = graph.add_node(NodeType.TASK, title="x", status="active")
    graph.update_node(nid, title="renamed")  # not a status→done change
    d = export_dashboard(graph)
    assert d["recent_done"] == []


def test_dashboard_recent_done_dedupes_done_to_done(graph):
    nid = graph.add_node(NodeType.TASK, title="x", status="done")
    # already done, then "completing" again should not register
    graph.update_node(nid, status="done")
    d = export_dashboard(graph)
    assert d["recent_done"] == []


# ---------- get_questions ----------

def _fake_response(payload):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))]
    )


def test_get_questions_returns_three(graph):
    graph.add_node(NodeType.TASK, title="купить хлеб", status="active", importance=7)
    questions = ["энергия?", "что важнее всего?", "что мешает?"]
    client = MagicMock()
    client.messages.create.return_value = _fake_response({"questions": questions})

    result = get_questions(graph, client=client)
    assert result["questions"] == questions
    assert "dashboard" in result
    assert result["dashboard"]["total_active"] == 1

    # The API call carries the schema and the cached system prompt
    args = client.messages.create.call_args.kwargs
    assert args["output_config"]["format"]["type"] == "json_schema"
    assert args["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "GTD-коуч" in args["system"][0]["text"]
    # Dashboard JSON is the user message
    user_payload = json.loads(args["messages"][0]["content"])
    assert "actionable" in user_payload


def test_get_questions_pads_when_fewer_than_three(graph):
    client = MagicMock()
    client.messages.create.return_value = _fake_response({"questions": ["только один"]})
    result = get_questions(graph, client=client)
    assert len(result["questions"]) == 3
    assert result["questions"][0] == "только один"


def test_get_questions_trims_when_more_than_three(graph):
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        {"questions": ["a", "b", "c", "d", "e"]}
    )
    result = get_questions(graph, client=client)
    assert result["questions"] == ["a", "b", "c"]


def test_get_questions_does_not_mutate_graph(graph):
    nid = graph.add_node(NodeType.TASK, title="untouched", status="active")
    before = dict(graph.get_node(nid))
    audit_len = len(graph.get_audit_log(limit=1000))

    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        {"questions": ["q1", "q2", "q3"]}
    )
    get_questions(graph, client=client)

    assert graph.get_node(nid) == before
    assert len(graph.get_audit_log(limit=1000)) == audit_len
