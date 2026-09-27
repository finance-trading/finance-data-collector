"""Unit tests for backend-owned catalog and generated data files."""

from __future__ import annotations

import json

from fdc.data_files import CATALOG_PATH, GRAPH_PATH, LAYERS_PATH, write_json_artifact
from fdc.sec_storage import PROJECT_ROOT


def test_data_paths_are_backend_owned():
    assert CATALOG_PATH == PROJECT_ROOT / "data" / "ai_companies.json"
    assert GRAPH_PATH == PROJECT_ROOT / "data" / "generated" / "graph.json"
    assert LAYERS_PATH == PROJECT_ROOT / "data" / "generated" / "layers.json"
    assert "web" not in GRAPH_PATH.parts


def test_write_json_artifact_writes_only_json(tmp_path):
    target = tmp_path / "nested" / "graph.json"

    output = write_json_artifact(target, {"nodes": [], "links": []})

    assert output == target
    assert json.loads(output.read_text()) == {"nodes": [], "links": []}
    assert not output.with_suffix(".js").exists()
