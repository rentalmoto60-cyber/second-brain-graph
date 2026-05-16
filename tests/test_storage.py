import json
import os

import pytest

from brain.storage import Storage


def test_load_missing_returns_empty(tmp_path):
    s = Storage(str(tmp_path / "missing.json"))
    assert s.exists() is False
    data = s.load_graph()
    assert data == {"nodes": [], "edges": [], "audit_log": []}


def test_round_trip(tmp_path):
    path = tmp_path / "brain.json"
    s = Storage(str(path))
    payload = {
        "nodes": [{"id": "n1", "title": "тест"}],
        "edges": [{"from": "n1", "to": "n1", "type": "BLOCKS"}],
        "audit_log": [{"action": "noop"}],
    }
    s.save_graph(payload)
    assert s.exists()
    loaded = s.load_graph()
    assert loaded == payload


def test_save_is_human_readable(tmp_path):
    path = tmp_path / "brain.json"
    s = Storage(str(path))
    s.save_graph({"nodes": [{"title": "русский"}], "edges": [], "audit_log": []})
    raw = path.read_text(encoding="utf-8")
    assert "\n" in raw
    assert "русский" in raw  # ensure_ascii=False


def test_atomic_write_no_partial_file(tmp_path, monkeypatch):
    """If serialization fails mid-write, no temp file should remain and the
    original file (if any) is untouched."""
    path = tmp_path / "brain.json"
    s = Storage(str(path))
    s.save_graph({"nodes": [{"id": "stable"}], "edges": [], "audit_log": []})
    original = path.read_text(encoding="utf-8")

    class Boom:
        def __repr__(self): raise RuntimeError("boom")

    with pytest.raises(Exception):
        s.save_graph({"nodes": [Boom()], "edges": [], "audit_log": []})

    # original survived
    assert path.read_text(encoding="utf-8") == original
    # no leftover tmp files in the dir
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".brain-")]
    assert leftovers == []


def test_load_fills_missing_keys(tmp_path):
    path = tmp_path / "brain.json"
    path.write_text(json.dumps({"nodes": [{"id": "x"}]}), encoding="utf-8")
    s = Storage(str(path))
    data = s.load_graph()
    assert data["nodes"] == [{"id": "x"}]
    assert data["edges"] == []
    assert data["audit_log"] == []
