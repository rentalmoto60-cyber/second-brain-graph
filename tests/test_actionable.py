from datetime import datetime, timedelta, timezone

import pytest

from brain.graph import BrainGraph
from brain.models import EdgeType, NodeType
from brain.storage import Storage


@pytest.fixture
def graph(tmp_path):
    return BrainGraph(Storage(str(tmp_path / "brain.json")))


def test_inbox_excluded(graph):
    graph.add_node(NodeType.TASK, title="inbox task")  # default status inbox
    assert graph.get_actionable() == []


def test_active_included(graph):
    graph.add_node(NodeType.TASK, title="t", status="active")
    out = graph.get_actionable()
    assert len(out) == 1
    assert out[0]["title"] == "t"
    assert "_computed_priority" in out[0]


def test_done_excluded(graph):
    graph.add_node(NodeType.TASK, title="t", status="done")
    assert graph.get_actionable() == []


def test_deleted_excluded(graph):
    nid = graph.add_node(NodeType.TASK, title="t", status="active")
    graph.soft_delete(nid)
    assert graph.get_actionable() == []


def test_blocked_excluded_when_blocker_open(graph):
    blocker = graph.add_node(NodeType.TASK, title="blocker", status="active")
    blocked = graph.add_node(NodeType.TASK, title="blocked", status="active")
    graph.add_edge(blocker, blocked, EdgeType.BLOCKS)
    out = graph.get_actionable()
    titles = [n["title"] for n in out]
    assert "blocked" not in titles
    assert "blocker" in titles


def test_blocked_included_when_blocker_done(graph):
    blocker = graph.add_node(NodeType.TASK, title="blocker", status="done")
    blocked = graph.add_node(NodeType.TASK, title="blocked", status="active")
    graph.add_edge(blocker, blocked, EdgeType.BLOCKS)
    titles = [n["title"] for n in graph.get_actionable()]
    assert titles == ["blocked"]


def test_sorted_by_priority_desc(graph):
    graph.add_node(NodeType.TASK, title="low", status="active", importance=1)
    graph.add_node(NodeType.TASK, title="high", status="active", importance=10)
    out = graph.get_actionable()
    assert [n["title"] for n in out] == ["high", "low"]
    assert out[0]["_computed_priority"] > out[1]["_computed_priority"]


def test_urgency_boost_for_near_deadline(graph):
    soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    far = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
    graph.add_node(NodeType.TASK, title="soon", status="active", importance=5, deadline=soon)
    graph.add_node(NodeType.TASK, title="far", status="active", importance=5, deadline=far)
    out = graph.get_actionable()
    assert out[0]["title"] == "soon"


def test_overdue_urgency_above_one(graph):
    overdue = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    nid = graph.add_node(NodeType.TASK, title="late", status="active", importance=1, deadline=overdue)
    score = BrainGraph._urgency_score(overdue, datetime.now(timezone.utc))
    assert score > 1.0
    assert graph.get_actionable()[0]["id"] == nid


def test_soft_time_filter_boosts_fitting(graph):
    short = graph.add_node(
        NodeType.TASK, title="short", status="active",
        importance=5, required_time_minutes=10,
    )
    long_ = graph.add_node(
        NodeType.TASK, title="long", status="active",
        importance=5, required_time_minutes=120,
    )
    out = graph.get_actionable(free_time_minutes=15, strict_time_filter=False)
    titles = [n["title"] for n in out]
    # both present
    assert set(titles) == {"short", "long"}
    # short is first (it got the boost)
    assert titles[0] == "short"


def test_strict_time_filter_excludes_too_long(graph):
    graph.add_node(NodeType.TASK, title="short", status="active",
                   importance=5, required_time_minutes=10)
    graph.add_node(NodeType.TASK, title="long", status="active",
                   importance=5, required_time_minutes=120)
    out = graph.get_actionable(free_time_minutes=15, strict_time_filter=True)
    assert [n["title"] for n in out] == ["short"]


def test_energy_penalty_lowers_priority(graph):
    a = graph.add_node(NodeType.TASK, title="light", status="active",
                       importance=5, energy="low")
    b = graph.add_node(NodeType.TASK, title="heavy", status="active",
                       importance=5, energy="high")
    out = graph.get_actionable()
    assert out[0]["title"] == "light"
    assert out[1]["title"] == "heavy"
