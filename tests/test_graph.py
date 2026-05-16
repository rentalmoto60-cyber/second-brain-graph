import pytest

from brain.graph import BrainGraph
from brain.models import EdgeType, NodeType, Status
from brain.storage import Storage


@pytest.fixture
def graph(tmp_path):
    return BrainGraph(Storage(str(tmp_path / "brain.json")))


# ---------- CRUD ----------

def test_add_task_minimal(graph):
    nid = graph.add_node(NodeType.TASK, title="write report")
    node = graph.get_node(nid)
    assert node["title"] == "write report"
    assert node["type"] == "task"
    assert node["status"] == Status.INBOX.value
    assert node["importance"] == 5
    assert node["created_at"] and node["updated_at"]


def test_add_task_with_string_node_type(graph):
    nid = graph.add_node("task", title="x")
    assert graph.get_node(nid)["type"] == "task"


def test_add_requires_title(graph):
    with pytest.raises(ValueError, match="title"):
        graph.add_node(NodeType.TASK)


@pytest.mark.parametrize("bad", [{"importance": 0}, {"importance": 11}, {"importance": "a"}])
def test_invalid_importance(graph, bad):
    with pytest.raises(ValueError, match="importance"):
        graph.add_node(NodeType.TASK, title="t", **bad)


def test_invalid_empty_title(graph):
    with pytest.raises(ValueError, match="title"):
        graph.add_node(NodeType.TASK, title="   ")


def test_invalid_negative_time(graph):
    with pytest.raises(ValueError, match="required_time"):
        graph.add_node(NodeType.TASK, title="t", required_time_minutes=-1)


def test_invalid_energy(graph):
    with pytest.raises(ValueError, match="energy"):
        graph.add_node(NodeType.TASK, title="t", energy="extreme")


def test_invalid_deadline(graph):
    with pytest.raises(ValueError, match="deadline"):
        graph.add_node(NodeType.TASK, title="t", deadline="tomorrow")


def test_update_node(graph):
    nid = graph.add_node(NodeType.TASK, title="t")
    graph.update_node(nid, title="new", importance=8)
    n = graph.get_node(nid)
    assert n["title"] == "new"
    assert n["importance"] == 8


def test_update_immutable_fields_rejected(graph):
    nid = graph.add_node(NodeType.TASK, title="t")
    for field in ("id", "created_at", "type"):
        with pytest.raises(ValueError, match="immutable"):
            graph.update_node(nid, **{field: "anything"})


def test_soft_delete_and_restore(graph):
    nid = graph.add_node(NodeType.TASK, title="t")
    graph.soft_delete(nid)
    assert graph.get_node(nid)["status"] == Status.DELETED.value
    graph.restore(nid)
    assert graph.get_node(nid)["status"] == Status.ACTIVE.value


def test_get_node_missing(graph):
    with pytest.raises(ValueError, match="not found"):
        graph.get_node("nope")


# ---------- edges ----------

def test_add_edge(graph):
    a = graph.add_node(NodeType.TASK, title="a")
    b = graph.add_node(NodeType.TASK, title="b")
    graph.add_edge(a, b, EdgeType.BLOCKS)


def test_blocks_self_loop_rejected(graph):
    a = graph.add_node(NodeType.TASK, title="a")
    with pytest.raises(ValueError, match="cycle"):
        graph.add_edge(a, a, EdgeType.BLOCKS)


def test_blocks_cycle_rejected(graph):
    a = graph.add_node(NodeType.TASK, title="a")
    b = graph.add_node(NodeType.TASK, title="b")
    c = graph.add_node(NodeType.TASK, title="c")
    graph.add_edge(a, b, EdgeType.BLOCKS)
    graph.add_edge(b, c, EdgeType.BLOCKS)
    with pytest.raises(ValueError, match="cycle"):
        graph.add_edge(c, a, EdgeType.BLOCKS)


def test_part_of_cycle_allowed(graph):
    """Only BLOCKS is acyclic; other edge types currently aren't checked."""
    a = graph.add_node(NodeType.TASK, title="a")
    b = graph.add_node(NodeType.TASK, title="b")
    graph.add_edge(a, b, EdgeType.PART_OF)
    graph.add_edge(b, a, EdgeType.PART_OF)


def test_remove_edge(graph):
    a = graph.add_node(NodeType.TASK, title="a")
    b = graph.add_node(NodeType.TASK, title="b")
    graph.add_edge(a, b, EdgeType.BLOCKS)
    graph.remove_edge(a, b, EdgeType.BLOCKS)


def test_remove_missing_edge(graph):
    a = graph.add_node(NodeType.TASK, title="a")
    b = graph.add_node(NodeType.TASK, title="b")
    with pytest.raises(ValueError, match="not found"):
        graph.remove_edge(a, b, EdgeType.BLOCKS)


# ---------- undo ----------

def test_undo_add_node(graph):
    nid = graph.add_node(NodeType.TASK, title="t")
    graph.undo_last_action()
    with pytest.raises(ValueError):
        graph.get_node(nid)


def test_undo_update_node(graph):
    nid = graph.add_node(NodeType.TASK, title="t", importance=3)
    graph.update_node(nid, title="changed", importance=9)
    graph.undo_last_action()
    n = graph.get_node(nid)
    assert n["title"] == "t"
    assert n["importance"] == 3


def test_undo_soft_delete(graph):
    nid = graph.add_node(NodeType.TASK, title="t", status="active")
    graph.soft_delete(nid)
    graph.undo_last_action()
    assert graph.get_node(nid)["status"] == "active"


def test_undo_restore(graph):
    nid = graph.add_node(NodeType.TASK, title="t", status="waiting")
    graph.restore(nid)
    graph.undo_last_action()
    assert graph.get_node(nid)["status"] == "waiting"


def test_undo_add_edge(graph):
    a = graph.add_node(NodeType.TASK, title="a")
    b = graph.add_node(NodeType.TASK, title="b")
    graph.add_edge(a, b, EdgeType.BLOCKS)
    graph.undo_last_action()
    # adding it again should succeed (i.e., previous one was undone)
    graph.add_edge(a, b, EdgeType.BLOCKS)


def test_undo_remove_edge(graph):
    a = graph.add_node(NodeType.TASK, title="a")
    b = graph.add_node(NodeType.TASK, title="b")
    graph.add_edge(a, b, EdgeType.BLOCKS)
    graph.remove_edge(a, b, EdgeType.BLOCKS)
    graph.undo_last_action()
    with pytest.raises(ValueError, match="already exists"):
        graph.add_edge(a, b, EdgeType.BLOCKS)


def test_undo_empty_stack(graph):
    with pytest.raises(ValueError, match="empty"):
        graph.undo_last_action()


def test_undo_stack_capped(graph):
    from brain.config import UNDO_STACK_LIMIT
    for i in range(UNDO_STACK_LIMIT + 5):
        graph.add_node(NodeType.TASK, title=f"t{i}")
    for _ in range(UNDO_STACK_LIMIT):
        graph.undo_last_action()
    # the 5 oldest add_node actions were evicted; their nodes remain
    assert sum(1 for _ in graph._g.nodes) == 5


# ---------- audit log ----------

def test_audit_log_records_mutations(graph):
    nid = graph.add_node(NodeType.TASK, title="t")
    graph.update_node(nid, title="t2")
    graph.soft_delete(nid)
    log = graph.get_audit_log()
    actions = [e["action"] for e in log]
    assert actions == ["add_node", "update_node", "soft_delete"]


def test_audit_log_records_undo(graph):
    graph.add_node(NodeType.TASK, title="t")
    graph.undo_last_action()
    assert graph.get_audit_log()[-1]["action"] == "undo_add_node"


def test_audit_log_limit(graph):
    for i in range(5):
        graph.add_node(NodeType.TASK, title=f"t{i}")
    assert len(graph.get_audit_log(limit=2)) == 2
    assert len(graph.get_audit_log(limit=100)) == 5


# ---------- persistence ----------

def test_save_and_load_roundtrip(tmp_path):
    storage = Storage(str(tmp_path / "brain.json"))
    g = BrainGraph(storage)
    a = g.add_node(NodeType.TASK, title="a", importance=7)
    b = g.add_node(NodeType.TASK, title="b")
    g.add_edge(a, b, EdgeType.BLOCKS)
    g.save()

    g2 = BrainGraph.load(storage)
    assert g2.get_node(a)["title"] == "a"
    assert g2.get_node(b)["title"] == "b"
    # cycle would arise if reload preserved the edge: try to add reverse blocks
    with pytest.raises(ValueError, match="cycle"):
        g2.add_edge(b, a, EdgeType.BLOCKS)
