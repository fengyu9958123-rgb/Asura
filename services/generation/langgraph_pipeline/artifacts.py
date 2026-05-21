"""Artifact helpers for the isolated LangGraph image pipeline."""

from __future__ import annotations

import json
import os
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .state import GraphPipelineState, public_state


class GraphArtifacts:
    """Read/write graph artifacts under an isolated output directory."""

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

    def read_text(self, relative_path: str) -> str:
        return (self.output_dir / relative_path).read_text(encoding="utf-8")

    def write_json(self, relative_path: str, payload: Any) -> str:
        path = Path(self.path(relative_path))
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def read_json(self, relative_path: str) -> Any:
        return json.loads((self.output_dir / relative_path).read_text(encoding="utf-8"))

    def write_state(self, state: GraphPipelineState) -> str:
        return self.write_json("graph_state.json", public_state(state))

    @contextmanager
    def node_result(self, node_name: str, state: GraphPipelineState) -> Iterator[Dict[str, Any]]:
        started_at = datetime.now().isoformat()
        started = time.time()
        result: Dict[str, Any] = {
            "node": node_name,
            "status": "running",
            "started_at": started_at,
            "finished_at": None,
            "duration_ms": None,
            "input_state": public_state(state),
            "output_state": None,
            "error": None,
        }
        self.write_json(f"nodes/{node_name}.result.json", result)
        try:
            yield result
            result["status"] = "success"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            raise
        finally:
            result["finished_at"] = datetime.now().isoformat()
            result["duration_ms"] = int((time.time() - started) * 1000)
            result["output_state"] = public_state(state)
            self.write_json(f"nodes/{node_name}.result.json", result)
            self.write_state(state)

    def write_node_result(self, node_name: str, result: Dict[str, Any]) -> str:
        return self.write_json(f"nodes/{node_name}.result.json", result)


def graph_output_dir(module_id: str) -> str:
    project_root = Path(__file__).resolve().parents[3]
    path = project_root / "outputs" / "image_pipeline_langgraph" / f"module_{module_id}"
    os.makedirs(path, exist_ok=True)
    return str(path)
