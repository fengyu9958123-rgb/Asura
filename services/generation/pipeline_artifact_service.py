"""
Artifact persistence for the structured testcase pipeline.

Agents only return content. This service is the only layer that writes stage
outputs to disk, which keeps retries and manual inspection straightforward.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


class PipelineArtifactService:
    """Read/write JSON and Markdown artifacts for one pipeline run."""

    def __init__(self, task_id: str, base_dir: Optional[str] = None):
        safe_task_id = self._safe_name(task_id)
        self.task_id = safe_task_id
        self.base_dir = base_dir or os.path.join("outputs", "testcase_pipeline", safe_task_id)
        os.makedirs(self.base_dir, exist_ok=True)
        self.index: Dict[str, Dict[str, Any]] = {}

    def write_text(self, relative_path: str, content: str, label: Optional[str] = None) -> str:
        path = self._resolve(relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
        self._record(label or relative_path, path, "text")
        return path

    def write_json(self, relative_path: str, data: Any, label: Optional[str] = None) -> str:
        path = self._resolve(relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._record(label or relative_path, path, "json")
        return path

    def read_text(self, relative_path: str) -> str:
        with open(self._resolve(relative_path), "r", encoding="utf-8") as f:
            return f.read()

    def read_json(self, relative_path: str) -> Any:
        with open(self._resolve(relative_path), "r", encoding="utf-8") as f:
            return json.load(f)

    def write_index(self) -> str:
        data = {
            "task_id": self.task_id,
            "base_dir": os.path.abspath(self.base_dir),
            "generated_at": datetime.now().isoformat(),
            "artifacts": self.index,
        }
        return self.write_json("artifact_index.json", data, "artifact_index")

    def _record(self, label: str, path: str, artifact_type: str) -> None:
        self.index[label] = {
            "path": os.path.abspath(path),
            "type": artifact_type,
            "updated_at": datetime.now().isoformat(),
        }

    def _resolve(self, relative_path: str) -> str:
        safe_parts = [self._safe_name(part) for part in relative_path.split("/") if part]
        path = os.path.abspath(os.path.join(self.base_dir, *safe_parts))
        base_abs = os.path.abspath(self.base_dir)
        if not path.startswith(base_abs + os.sep) and path != base_abs:
            raise ValueError(f"artifact path escapes base dir: {relative_path}")
        return path

    @staticmethod
    def _safe_name(value: str) -> str:
        keep = []
        for char in str(value):
            if char.isalnum() or char in ("_", "-", "."):
                keep.append(char)
            else:
                keep.append("_")
        return "".join(keep).strip("._") or "artifact"
