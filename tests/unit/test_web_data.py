"""Unit tests for the viewer payload writer (JSON + ``file://`` script shim)."""

from __future__ import annotations

import json

from fdc.web_data import GLOBAL, write_data


def test_write_data_writes_json_and_script_shim(tmp_path):
    payload = {"root": {"name": "AI 产业链"}, "stats": {"companies": 3}}

    json_path, js_path = write_data("layers", payload, tmp_path)

    assert json_path == tmp_path / "layers.json"
    assert js_path == tmp_path / "layers.js"
    assert json.loads(json_path.read_text()) == payload

    shim = js_path.read_text()
    assert f"window.{GLOBAL} = window.{GLOBAL} || {{}};" in shim
    assert f'window.{GLOBAL}["layers"] = {{' in shim
    assert '"name": "AI 产业链"' in shim


def test_write_data_creates_missing_directory(tmp_path):
    target = tmp_path / "nested" / "data"

    json_path, js_path = write_data("graph", {"nodes": [], "links": []}, target)

    assert json_path.exists() and js_path.exists()
