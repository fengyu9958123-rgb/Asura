"""Service entrypoint for the isolated LangGraph image pipeline."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from database.models import DatabaseManager, RequirementModule

from .artifacts import GraphArtifacts, graph_output_dir
from .graph import build_graph
from .nodes import GraphPipelineNodes
from .state import GraphPipelineState


class LangGraphImagePipelineService:
    """Run the experimental isolated LangGraph image pipeline."""

    def run(
        self,
        module_id: str,
        task_id: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        output_dir = graph_output_dir(str(module_id))
        nodes = GraphPipelineNodes(output_dir, progress_callback=progress_callback)
        graph = build_graph(nodes, resume=False)
        state: GraphPipelineState = {
            "module_id": str(module_id),
            "task_id": task_id or f"lg_{module_id}",
            "output_dir": output_dir,
            "phase": "pre_confirmation",
            "status": "running",
        }
        result = graph.invoke(state)
        GraphArtifacts(output_dir).write_state(result)
        return dict(result)

    def resume(
        self,
        module_id: str,
        answers_path: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        output_dir = graph_output_dir(str(module_id))
        artifacts = GraphArtifacts(output_dir)
        state_path = Path(output_dir) / "graph_state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"graph state not found: {state_path}")
        state: GraphPipelineState = json.loads(state_path.read_text(encoding="utf-8"))
        answers_file = Path(answers_path) if answers_path else Path(output_dir) / "confirmation" / "answers.json"
        if not answers_file.exists() and state.get("needs_confirmation"):
            raise FileNotFoundError(f"confirmation answers not found: {answers_file}")
        if answers_file.exists():
            state["confirmation_answers_path"] = str(answers_file)
            state["confirmation_answers"] = json.loads(answers_file.read_text(encoding="utf-8"))
        state["status"] = "running"
        state["phase"] = "post_confirmation"
        state.pop("error", None)
        nodes = GraphPipelineNodes(output_dir, progress_callback=progress_callback)
        graph = build_graph(nodes, resume=True)
        result = graph.invoke(state)
        artifacts.write_state(result)
        return dict(result)


class LangGraphImagePipelineRuntimeService:
    """DB-backed runtime adapter for using the LangGraph pipeline from the existing UI."""

    def __init__(self):
        self.db_manager = DatabaseManager()
        self.db_manager.initialize()

    def start_generation(self, module_id: str, user_id: str = "system") -> Dict[str, Any]:
        module_id = str(module_id)
        module = self._get_module(module_id)
        if not module.images or len(module.images or []) == 0:
            raise ValueError("需求模块没有上传图片")
        if module.status in ["processing", "waiting_confirmation"]:
            raise ValueError("任务正在处理中，请勿重复启动")

        task_id = f"img_task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        self._update_module(
            module_id,
            status="processing",
            task_id=task_id,
            generated_task_id=task_id,
            processing_stage="initializing",
            progress=0,
            error_message=None,
            error_stage=None,
            confirmation_questions=None,
            confirmation_answers=None,
            prd_final_content=None,
            test_analysis=None,
            test_cases_raw=None,
            test_cases_json=None,
            generation_result=None,
        )
        thread = threading.Thread(
            target=self._run_background,
            args=(module_id, task_id, user_id),
            daemon=True,
        )
        thread.start()
        return {
            "task_id": task_id,
            "module_id": module_id,
            "status": "processing",
            "message": "图片需求任务启动成功（LangGraph）",
        }

    def continue_after_confirmation(self, module_id: str, user_answers: Dict[str, str]) -> None:
        module_id = str(module_id)
        module = self._get_module(module_id)
        task_id = module.task_id or module.generated_task_id
        if not task_id:
            raise ValueError(f"模块 {module_id} 没有关联的任务ID")
        output_dir = graph_output_dir(module_id)
        answers_path = Path(output_dir) / "confirmation" / "answers.json"
        answers_path.parent.mkdir(parents=True, exist_ok=True)
        answers_path.write_text(json.dumps(user_answers or {}, ensure_ascii=False, indent=2), encoding="utf-8")
        self._update_module(
            module_id,
            status="processing",
            processing_stage="integrating_confirmations",
            progress=58,
            confirmation_answers=json.dumps(user_answers or {}, ensure_ascii=False),
            error_message=None,
            error_stage=None,
        )
        thread = threading.Thread(
            target=self._resume_background,
            args=(module_id, task_id, str(answers_path)),
            daemon=True,
        )
        thread.start()

    def _run_background(self, module_id: str, task_id: str, user_id: str) -> None:
        try:
            self._update_module(module_id, processing_stage="analyzing_images", progress=10)
            result = LangGraphImagePipelineService().run(
                module_id,
                task_id=task_id,
                progress_callback=lambda stage, progress, message="": self._sync_progress(module_id, stage, progress, message),
            )
            if result.get("status") == "waiting_confirmation":
                self._sync_waiting_confirmation(module_id, result)
                return
            self._sync_completed(module_id, result)
        except Exception as exc:
            self._mark_failed(module_id, str(exc))

    def _resume_background(self, module_id: str, task_id: str, answers_path: str) -> None:
        try:
            result = LangGraphImagePipelineService().resume(
                module_id,
                answers_path=answers_path,
                progress_callback=lambda stage, progress, message="": self._sync_progress(module_id, stage, progress, message),
            )
            self._sync_completed(module_id, result)
        except Exception as exc:
            self._mark_failed(module_id, str(exc))

    def _sync_progress(self, module_id: str, stage: str, progress: int, message: str = "") -> None:
        self._update_module(
            module_id,
            status="processing",
            processing_stage=stage,
            progress=progress,
            error_message=None,
            error_stage=None,
        )

    def _sync_waiting_confirmation(self, module_id: str, state: Dict[str, Any]) -> None:
        questions = self._read_json_path(state.get("confirmation_items_path"), default=[])
        prd_content = self._read_text_path(state.get("prd_draft_path"))
        analyses = self._read_json_path(state.get("image_analysis_path"), default={})
        self._update_module(
            module_id,
            status="waiting_confirmation",
            processing_stage="reviewing_prd",
            progress=55,
            module_analyses=json.dumps(analyses, ensure_ascii=False),
            prd_version_content=prd_content,
            prd_file_path=state.get("prd_draft_path"),
            confirmation_questions=json.dumps(questions, ensure_ascii=False),
            confirmation_answers=None,
            generation_result={
                "pipeline": "langgraph",
                "output_dir": state.get("output_dir"),
                "graph_state": str(Path(state.get("output_dir", "")) / "graph_state.json") if state.get("output_dir") else "",
            },
        )

    def _sync_completed(self, module_id: str, state: Dict[str, Any]) -> None:
        final_prd = self._read_text_path(state.get("final_prd_path"))
        test_results = state.get("test_results") if isinstance(state.get("test_results"), dict) else {}
        if not test_results:
            test_results = self._read_json_path(state.get("test_results_path"), default={})
        if not test_results:
            fallback_path = Path(state.get("output_dir", "")) / "testcase_pipeline" / "test_results.json"
            test_results = self._read_json_path(str(fallback_path), default={})
        testcases = test_results.get("testcases_list") or test_results.get("testcases") or []
        self._update_module(
            module_id,
            status="completed",
            processing_stage="completed",
            progress=100,
            prd_final_content=final_prd,
            prd_file_path=state.get("final_prd_path") or state.get("prd_draft_path"),
            test_analysis=test_results.get("test_analysis", ""),
            test_cases_raw=test_results.get("testcases_raw", ""),
            test_cases_json=json.dumps(testcases, ensure_ascii=False, indent=2),
            error_message=None,
            error_stage=None,
            generation_result={
                "pipeline": "langgraph",
                "output_dir": state.get("output_dir"),
                "result_index": state.get("result_index_path"),
                "artifact_dir": test_results.get("artifact_dir") or state.get("testcase_artifact_dir"),
                "artifact_index": test_results.get("artifact_index") or state.get("testcase_artifact_index"),
            },
        )

    def _mark_failed(self, module_id: str, error: str) -> None:
        module = self._get_module(module_id)
        self._update_module(
            module_id,
            status="failed",
            error_message=error,
            error_stage=module.processing_stage,
        )

    def _get_module(self, module_id: str) -> RequirementModule:
        session = self.db_manager.get_session()
        try:
            module = session.query(RequirementModule).filter_by(id=str(module_id)).first()
            if not module:
                raise ValueError(f"需求模块不存在: {module_id}")
            session.expunge(module)
            return module
        finally:
            session.close()

    def _update_module(self, module_id: str, **kwargs: Any) -> None:
        session = self.db_manager.get_session()
        try:
            module = session.query(RequirementModule).filter_by(id=str(module_id)).first()
            if not module:
                raise ValueError(f"需求模块不存在: {module_id}")
            for key, value in kwargs.items():
                setattr(module, key, value)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _read_text_path(path: Optional[str]) -> str:
        if not path:
            return ""
        file_path = Path(path)
        return file_path.read_text(encoding="utf-8") if file_path.exists() else ""

    @staticmethod
    def _read_json_path(path: Optional[str], default: Any) -> Any:
        if not path:
            return default
        file_path = Path(path)
        if not file_path.exists():
            return default
        return json.loads(file_path.read_text(encoding="utf-8"))
