import math
import os

import pytest

from brain.config import LOBE_CENTERS, LOBE_SPREAD, TAG_TO_LOBE
from brain.graph import BrainGraph
from brain.models import NodeType
from brain.storage import Storage
from brain.visualizer import compute_3d_positions, export_graph


@pytest.fixture
def graph(tmp_path):
    return BrainGraph(Storage(str(tmp_path / "brain.json")))


def test_position_inside_lobe_when_tag_matches(graph):
    nid = graph.add_node(NodeType.TASK, title="t", tags=["проект"])
    pos = compute_3d_positions(graph)[nid]
    centers = LOBE_CENTERS["frontal"]
    dl = math.dist(pos, centers["left"])
    dr = math.dist(pos, centers["right"])
    # Position should be within a few sigmas of one of the frontal centers.
    assert min(dl, dr) < 5 * LOBE_SPREAD


def test_default_lobe_when_no_tags(graph):
    nid = graph.add_node(NodeType.TASK, title="t")
    pos = compute_3d_positions(graph)[nid]
    default_lobe = TAG_TO_LOBE["_default"]
    centers = LOBE_CENTERS[default_lobe]
    best = min(math.dist(pos, c) for c in centers.values())
    assert best < 5 * LOBE_SPREAD


def test_positions_are_deterministic(graph):
    nid = graph.add_node(NodeType.TASK, title="t", tags=["работа"])
    a = compute_3d_positions(graph)[nid]
    b = compute_3d_positions(graph)[nid]
    assert a == b


def test_positions_survive_save_load(tmp_path):
    storage = Storage(str(tmp_path / "brain.json"))
    g = BrainGraph(storage)
    nid = g.add_node(NodeType.TASK, title="t", tags=["работа"])
    before = compute_3d_positions(g)[nid]
    g.save()
    g2 = BrainGraph.load(storage)
    after = compute_3d_positions(g2)[nid]
    assert before == after


def test_export_graph_shape(graph):
    a = graph.add_node(NodeType.TASK, title="a", tags=["работа"])
    b = graph.add_node(NodeType.TASK, title="b")
    graph.add_edge(a, b, "BLOCKS")
    out = export_graph(graph)
    assert {n["id"] for n in out["nodes"]} == {a, b}
    for n in out["nodes"]:
        assert "position" in n
        assert set(n["position"].keys()) == {"x", "y", "z"}
    assert out["edges"] == [{"from": a, "to": b, "type": "BLOCKS"}]


def test_unknown_tag_falls_back_to_default(graph):
    nid = graph.add_node(NodeType.TASK, title="t", tags=["zzzz_unknown"])
    pos = compute_3d_positions(graph)[nid]
    default_lobe = TAG_TO_LOBE["_default"]
    centers = LOBE_CENTERS[default_lobe]
    best = min(math.dist(pos, c) for c in centers.values())
    assert best < 5 * LOBE_SPREAD
