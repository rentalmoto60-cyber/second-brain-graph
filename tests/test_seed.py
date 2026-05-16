import pytest
from fastapi.testclient import TestClient

from brain.api import create_app
from brain.graph import BrainGraph
from brain.seed import DEMO_NODES, seed_demo_nodes
from brain.storage import Storage


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_DEMO_NODES", "1")
    return BrainGraph(Storage(str(tmp_path / "brain.json")))


def test_seed_populates_empty_graph(graph):
    ids = seed_demo_nodes(graph)
    assert len(ids) == len(DEMO_NODES)
    assert graph._g.number_of_nodes() == len(DEMO_NODES)
    titles = {n["title"] for _, n in graph._g.nodes(data=True)}
    assert "Подготовить отчёт по объекту №4" in titles


def test_seed_is_idempotent(graph):
    seed_demo_nodes(graph)
    seed_demo_nodes(graph)
    assert graph._g.number_of_nodes() == len(DEMO_NODES)


def test_seed_skipped_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_DEMO_NODES", "0")
    g = BrainGraph(Storage(str(tmp_path / "brain.json")))
    assert seed_demo_nodes(g) == []
    assert g._g.number_of_nodes() == 0


def test_seed_skipped_when_graph_has_a_deleted_node(graph):
    nid = graph.add_node("task", title="someone was here")
    graph.soft_delete(nid)
    seed_demo_nodes(graph)
    # exactly 1 node — seed must not run alongside existing data
    assert graph._g.number_of_nodes() == 1


def test_lifespan_seeds_on_first_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_DEMO_NODES", "1")
    db = str(tmp_path / "brain.json")
    app = create_app(db_path=db)
    with TestClient(app) as c:
        graph = c.get("/api/graph").json()
        assert len(graph["nodes"]) == len(DEMO_NODES)


def test_lifespan_does_not_reseed_after_user_deletes(tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_DEMO_NODES", "1")
    db = str(tmp_path / "brain.json")
    # First run: seed populates the graph
    with TestClient(create_app(db_path=db)) as c:
        nodes = c.get("/api/graph").json()["nodes"]
        assert len(nodes) == len(DEMO_NODES)
        for n in nodes:
            c.delete(f"/api/nodes/{n['id']}")
    # Second run: storage still contains the (soft-deleted) seeded nodes → no
    # new ones must be created.
    with TestClient(create_app(db_path=db)) as c:
        nodes = c.get("/api/graph").json()["nodes"]
        assert len(nodes) == len(DEMO_NODES)
        assert all(n["status"] == "deleted" for n in nodes)
