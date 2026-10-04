"""Canonical and generated repository data paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fdc.sec_storage import PROJECT_ROOT

DATA_ROOT = PROJECT_ROOT / "data"
CATALOG_PATH = DATA_ROOT / "ai_companies.json"
GENERATED_DATA_DIR = DATA_ROOT / "generated"
GRAPH_PATH = GENERATED_DATA_DIR / "graph.json"
LAYERS_PATH = GENERATED_DATA_DIR / "layers.json"
QUOTES_PATH = GENERATED_DATA_DIR / "quotes.json"


def write_json_artifact(path: Path, payload: dict[str, Any]) -> Path:
    """Write one backend-owned JSON artifact and return its path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    return path
