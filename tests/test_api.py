import json
import os

import pytest
from fastapi.testclient import TestClient

from brain.api import create_app


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "brain.json")
    app = create_app(db_path=db)
    with TestClient(app) as c:
        yield c


def test_empty_graph(client):
    r = client.get("/api/graph")
    assert r.status_code == 200
    assert r.json() == {"nodes": [], "edges": []}


def test_create_and_fetch_node(client):
    r = client.post("/api/nodes", json={
        "type": "task", "title": "first", "status": "active", "importance": 7,
    })
    assert r.status_code == 200
    nid = r.json()["id"]

    graph = client.get("/api/graph").json()
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["title"] == "first"
    assert "position" in graph["nodes"][0]


def test_create_invalid_node_400(client):
    r = client.post("/api/nodes", json={"type": "task", "title": ""})
    assert r.status_code == 400


def test_patch_node(client):
    nid = client.post("/api/nodes", json={"type": "task", "title": "x"}).json()["id"]
    r = client.patch(f"/api/nodes/{nid}", json={"title": "renamed", "importance": 9})
    assert r.status_code == 200
    assert r.json()["title"] == "renamed"
    assert r.json()["importance"] == 9


def test_patch_immutable_field_400(client):
    nid = client.post("/api/nodes", json={"type": "task", "title": "x"}).json()["id"]
    r = client.patch(f"/api/nodes/{nid}", json={"id": "spoofed"})
    assert r.status_code == 400


def test_delete_and_restore(client):
    nid = client.post("/api/nodes", json={"type": "task", "title": "x"}).json()["id"]
    assert client.delete(f"/api/nodes/{nid}").status_code == 200
    g = client.get("/api/graph").json()
    assert g["nodes"][0]["status"] == "deleted"
    assert client.post(f"/api/nodes/{nid}/restore").status_code == 200
    g = client.get("/api/graph").json()
    assert g["nodes"][0]["status"] == "active"


def test_edge_lifecycle(client):
    a = client.post("/api/nodes", json={"type": "task", "title": "a"}).json()["id"]
    b = client.post("/api/nodes", json={"type": "task", "title": "b"}).json()["id"]
    assert client.post("/api/edges", json={"from": a, "to": b, "type": "BLOCKS"}).status_code == 200
    g = client.get("/api/graph").json()
    assert g["edges"] == [{"from": a, "to": b, "type": "BLOCKS"}]
    r = client.request("DELETE", "/api/edges", json={"from": a, "to": b, "type": "BLOCKS"})
    assert r.status_code == 200
    assert client.get("/api/graph").json()["edges"] == []


def test_edge_cycle_rejected(client):
    a = client.post("/api/nodes", json={"type": "task", "title": "a"}).json()["id"]
    b = client.post("/api/nodes", json={"type": "task", "title": "b"}).json()["id"]
    client.post("/api/edges", json={"from": a, "to": b, "type": "BLOCKS"})
    r = client.post("/api/edges", json={"from": b, "to": a, "type": "BLOCKS"})
    assert r.status_code == 400


def test_actionable_endpoint(client):
    client.post("/api/nodes", json={"type": "task", "title": "a", "status": "active", "importance": 8})
    client.post("/api/nodes", json={"type": "task", "title": "b", "status": "inbox"})
    out = client.get("/api/actionable").json()
    titles = [n["title"] for n in out]
    assert titles == ["a"]


def test_actionable_strict_filter(client):
    client.post("/api/nodes", json={
        "type": "task", "title": "short", "status": "active",
        "required_time_minutes": 5,
    })
    client.post("/api/nodes", json={
        "type": "task", "title": "long", "status": "active",
        "required_time_minutes": 120,
    })
    out = client.get("/api/actionable?free_time=10&strict=true").json()
    assert [n["title"] for n in out] == ["short"]


def test_undo(client):
    nid = client.post("/api/nodes", json={"type": "task", "title": "x"}).json()["id"]
    client.post("/api/undo")
    g = client.get("/api/graph").json()
    assert g["nodes"] == []


def test_audit_endpoint(client):
    client.post("/api/nodes", json={"type": "task", "title": "x"})
    log = client.get("/api/audit?limit=10").json()
    assert log[-1]["action"] == "add_node"


def test_websocket_broadcast_on_mutation(client):
    with client.websocket_connect("/ws") as ws:
        client.post("/api/nodes", json={"type": "task", "title": "ping"})
        msg = ws.receive_json()
        assert msg == {"type": "graph_changed"}


def test_persistence_across_app_instances(tmp_path):
    db = str(tmp_path / "brain.json")
    app1 = create_app(db_path=db)
    with TestClient(app1) as c:
        c.post("/api/nodes", json={"type": "task", "title": "persisted"})

    app2 = create_app(db_path=db)
    with TestClient(app2) as c:
        nodes = c.get("/api/graph").json()["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["title"] == "persisted"
