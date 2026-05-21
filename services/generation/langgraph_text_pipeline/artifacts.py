"""Artifact helpers for the isolated LangGraph text PRD pipeline."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .state import TextGraphPipelineState, public_state


class TextGraphArtifacts:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "nodes").mkdir(parents=True, exist_ok=True)

    def path(self, relative_path: str) -> str:
        path = self.output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def write_text(self, relative_path: str, content: str) -> str:
        path = Path(self.path(relative_path))
        path.write_text(str(content or ""), encoding="utf-8")
        return str(path)

    def write_json(self, relative_path: str, payload: Any) -> str:
        path = Path(self.path(relative_path))
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def write_state(self, state: TextGraphPipelineState) -> str:
        return self.write_json("graph_state.json", public_state(state))

    def write_node_result(self, node_name: str, result: Dict[str, Any]) -> str:
        return self.write_json(f"nodes/{node_name}.result.json", result)

    @staticmethod
    def begin_node_record(node_name: str, state: TextGraphPipelineState) -> Dict[str, Any]:
        return {
            "node": node_name,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "duration_ms": None,
            "input_state": public_state(state),
            "updates": None,
            "output_state": None,
            "error": None,
        }


def graph_output_dir(task_id: str) -> str:
    project_root = Path(__file__).resolve().parents[3]
    path = project_root / "outputs" / "text_pipeline_langgraph" / f"task_{task_id}"
    os.makedirs(path, exist_ok=True)
    return str(path)
