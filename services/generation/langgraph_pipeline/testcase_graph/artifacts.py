"""Artifact helpers for the isolated testcase LangGraph subgraph."""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .state import TestcaseGraphState, public_state


class TestcaseGraphArtifacts:
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

    def write_state(self, state: TestcaseGraphState) -> str:
        return self.write_json("graph_state.json", public_state(state))

    def write_node_result(self, node_name: str, result: Dict[str, Any]) -> str:
        return self.write_json(f"nodes/{node_name}.result.json", result)

    def begin_result(self, node_name: str, state: TestcaseGraphState) -> Dict[str, Any]:
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

    def finalize_result(
        self,
        result: Dict[str, Any],
        *,
        updates: Dict[str, Any] | None,
        state: TestcaseGraphState,
        started: float,
        error: Exception | None = None,
    ) -> None:
        if error is None:
            result["status"] = "success"
            result["updates"] = public_state(updates or {})
        else:
            result["status"] = "failed"
            result["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        result["finished_at"] = datetime.now().isoformat()
        result["duration_ms"] = int((time.time() - started) * 1000)
        result["output_state"] = public_state(state)
        self.write_node_result(result["node"], result)
        self.write_state(state)
