"""LangGraph-style nodes for the isolated image pipeline.

Each node returns state updates instead of mutating and returning the full state.
The node wrapper handles bookkeeping, artifact snapshots and error records.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict

from services.generation.image_pipeline_service import ImagePipelineService
from services.generation.llm_usage import UsageRecorder, usage_context
from services.notifications.unified_task_logger import UnifiedTaskLogger

from .artifacts import GraphArtifacts
from .state import GraphPipelineState, public_state
from .testcase_graph import TestcaseGraphNodes, build_graph as build_testcase_graph


class LegacyStageLoggerAdapter:
    """Provide the legacy stage_loggers interface expected by stage methods."""

    STAGE_LABELS = {
        "stage1": "image_analysis",
        "stage2": "prd_generation",
        "stage3": "prd_review",
        "stage5": "confirmation_integrate",
        "stage6": "testcase_pipeline",
    }

    def __init__(self, task_id: str):
        self._logger = UnifiedTaskLogger(task_id, "langgraph_image_pipeline")
        self.stage_loggers = {}
        self._ensure_stage_loggers()

    def _ensure_stage_loggers(self) -> None:
        for stage_key, stage_label in self.STAGE_LABELS.items():
            if stage_key in self.stage_loggers:
                continue
            log_file = os.path.join(self._logger.stages_dir, f"{stage_key}_{stage_label}.log")
            self.stage_loggers[stage_key] = self._logger._create_logger(stage_key, log_file)

    def log_performance_metric(self, metric_name: str, value: float, unit: str = ""):
        self._logger.log_performance_metric(metric_name, value, unit)

    def save_ai_response(self, agent_name: str, prompt: str, response: str, metadata: Dict[str, Any] | None = None):
        self._logger.save_ai_response(agent_name, prompt, response, metadata)


class IsolatedImagePipelineService(ImagePipelineService):
    """Reuse existing stages while isolating output files and DB writes."""

    def __init__(self, output_dir: str):
        super().__init__()
        self._isolated_output_dir = output_dir

    def _get_output_dir(self, module_id: int) -> str:
        os.makedirs(self._isolated_output_dir, exist_ok=True)
        return self._isolated_output_dir

    def _update_progress(self, module_id: int, stage: str, progress: int, message: str = ""):
        return None

    def _update_module(self, module_id: int, **kwargs):
        return None

    def _update_task(self, task_id: str, **kwargs):
        return None

    def _mark_complete(self, module_id: int, task_id: str):
        return None

    def _mark_failed(self, module_id: int, task_id: str, error_msg: str):
        return None


class GraphPipelineNodes:
    def __init__(self, output_dir: str, progress_callback: Callable[[str, int, str], None] | None = None):
        self.artifacts = GraphArtifacts(output_dir)
        self.stage_service = IsolatedImagePipelineService(output_dir)
        self._loggers: Dict[str, LegacyStageLoggerAdapter] = {}
        self.progress_callback = progress_callback
        self.usage_recorder = UsageRecorder(output_dir)

    def _progress(self, stage: str, progress: int, message: str = "") -> None:
        if not self.progress_callback:
            return
        self.progress_callback(stage, progress, message)

    def node(self, node_name: str) -> Callable:
        """Wrap a node function with artifact logging and state persistence."""

        def decorator(func: Callable[[GraphPipelineState], Dict[str, Any]]) -> Callable[[GraphPipelineState], Dict[str, Any]]:
            @wraps(func)
            def wrapped(state: GraphPipelineState) -> Dict[str, Any]:
                started_at = datetime.now().isoformat()
                started = time.time()
                base_updates = {
                    "current_node": node_name,
                    "status": "running",
                }
                running_state = {**dict(state), **base_updates}
                result_record: Dict[str, Any] = {
                    "node": node_name,
                    "status": "running",
                    "started_at": started_at,
                    "finished_at": None,
                    "duration_ms": None,
                    "input_state": public_state(running_state),
                    "updates": None,
                    "output_state": None,
                    "error": None,
                }
                self.artifacts.write_node_result(node_name, result_record)
                try:
                    updates = func(running_state) or {}
                    result_record["status"] = "success"
                    result_record["updates"] = public_state(updates)
                    next_state = {**running_state, **updates}
                    return {**base_updates, **updates}
                except Exception as exc:
                    result_record["status"] = "failed"
                    result_record["error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    next_state = {**running_state, "status": "failed", "error": str(exc)}
                    raise
                finally:
                    result_record["finished_at"] = datetime.now().isoformat()
                    result_record["duration_ms"] = int((time.time() - started) * 1000)
                    result_record["output_state"] = public_state(next_state)
                    self.artifacts.write_node_result(node_name, result_record)
                    self.artifacts.write_state(next_state)

            return wrapped

        return decorator

    def load_module(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("01_load_module")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            module_id = state["module_id"]
            module = self.stage_service._get_module(module_id)
            self.artifacts.write_json("module.json", module.to_dict())
            return {
                "module_name": module.name,
                "task_id": state.get("task_id") or f"lg_{module_id}",
                "output_dir": str(self.artifacts.output_dir),
                "phase": state.get("phase") or "pre_confirmation",
            }

        return _node

    def image_analysis(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("02_image_analysis")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            self._progress("analyzing_images", 10, "正在分析图片...")
            with usage_context(self.usage_recorder, "02_image_analysis"):
                analyses = self.stage_service._stage1_analyze_images(state["module_id"], self._logger(state))
            return {
                "image_analyses": analyses,
                "image_analysis_path": self.artifacts.write_json("image_analysis/analysis.json", analyses),
            }

        return _node

    def prd_generation(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("03_prd_generation")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            self._progress("generating_prd", 30, "正在生成PRD文档...")
            analyses = state.get("image_analyses")
            if not analyses and state.get("image_analysis_path"):
                analyses = self._read_json(state["image_analysis_path"])
            with usage_context(self.usage_recorder, "03_prd_generation"):
                prd_content, _prd_file = self.stage_service._stage2_generate_prd(
                    state["module_id"], analyses, self._logger(state)
                )
            return {
                "prd_content": prd_content,
                "prd_draft_path": self.artifacts.write_text("prd/01_draft_prd.md", prd_content),
            }

        return _node

    def prd_review(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("04_prd_review")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            self._progress("reviewing_prd", 50, "正在审核PRD文档...")
            prd_content = state.get("prd_content") or self._read_text(state["prd_draft_path"])
            with usage_context(self.usage_recorder, "04_prd_review"):
                questions = self.stage_service._stage3_review_prd(
                    state["module_id"], prd_content, self._logger(state)
                )
            return {
                "confirmation_items": questions,
                "prd_review_path": self.artifacts.write_json("prd/02_review_result.json", {"confirmation_items": questions}),
                "confirmation_items_path": self.artifacts.write_json("confirmation/items.json", questions),
                "needs_confirmation": bool(questions),
            }

        return _node

    def wait_for_confirmation(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("05_waiting_confirmation")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            self._progress("waiting_confirmation", 55, "等待人工确认...")
            return {
                "phase": "waiting_confirmation",
                "status": "waiting_confirmation",
            }

        return _node

    def confirmation_integrate(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("06_confirmation_integrate")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            self._progress("integrating_confirmations", 60, "正在整合确认结果...")
            prd_content = state.get("prd_content") or self._read_text(state["prd_draft_path"])
            questions = state.get("confirmation_items")
            if questions is None and state.get("confirmation_items_path"):
                questions = self._read_json(state["confirmation_items_path"])
            answers = state.get("confirmation_answers")
            if answers is None and state.get("confirmation_answers_path"):
                answers = self._read_json(state["confirmation_answers_path"])
            if questions:
                with usage_context(self.usage_recorder, "06_confirmation_integrate"):
                    final_prd = self.stage_service._stage5_integrate_confirmations(
                        state["module_id"], prd_content, questions, answers or {}, self._logger(state)
                    )
            else:
                final_prd = prd_content
            return {
                "final_prd": final_prd,
                "final_prd_path": self.artifacts.write_text("prd/04_final_prd.md", final_prd),
                "phase": "post_confirmation",
            }

        return _node

    def testcase_pipeline(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("07_testcase_pipeline")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            self._progress("generating_testcases", 65, "正在生成测试用例...")
            final_prd = state.get("final_prd") or self._read_text(state["final_prd_path"])
            module = self.stage_service._get_module(state["module_id"])
            notes_mgr = self.stage_service._get_notes_manager(module)
            testing_notes = ""
            if notes_mgr and notes_mgr.has_notes():
                testing_notes = notes_mgr.get_notes_for_stage("测试补充")
            testcase_output_dir = str(Path(self.artifacts.output_dir) / "testcase_pipeline")
            testcase_nodes = TestcaseGraphNodes(
                testcase_output_dir,
                progress_callback=self.progress_callback,
                usage_recorder=self.usage_recorder,
            )
            testcase_graph = build_testcase_graph(testcase_nodes)
            testcase_state = {
                "module_id": state["module_id"],
                "task_name": state.get("module_name") or module.name,
                "final_prd": final_prd,
                "testing_notes": testing_notes,
                "output_dir": testcase_output_dir,
                "status": "running",
            }
            testcase_result_state = testcase_graph.invoke(testcase_state)
            test_results = testcase_result_state.get("test_results") or {}
            testcase_path = test_results.get("artifact_index") or test_results.get("artifact_dir") or ""
            return {
                "test_results": test_results,
                "test_cases_path": str(testcase_path),
                "test_results_path": testcase_result_state.get("test_results_path", ""),
                "testcase_artifact_dir": test_results.get("artifact_dir", ""),
                "testcase_artifact_index": test_results.get("artifact_index", ""),
            }

        return _node

    def save_result(self) -> Callable[[GraphPipelineState], Dict[str, Any]]:
        @self.node("08_save_result")
        def _node(state: GraphPipelineState) -> Dict[str, Any]:
            self._progress("saving_results", 95, "正在保存生成结果...")
            test_results = state.get("test_results") or {}
            result = {
                "module_id": state.get("module_id"),
                "module_name": state.get("module_name"),
                "status": "completed",
                "final_prd_path": state.get("final_prd_path"),
                "test_cases_path": state.get("test_cases_path"),
                "testcases_count": len(test_results.get("testcases_list") or []),
                "artifact_dir": test_results.get("artifact_dir"),
                "artifact_index": test_results.get("artifact_index"),
                "usage_summary_path": str(self.usage_recorder.summary_path),
                "usage_records_path": str(self.usage_recorder.records_path),
                "usage_summary": self.usage_recorder.summarize(self.usage_recorder.read_records()),
                "note": "isolated LangGraph experiment; legacy DB result fields are not updated",
            }
            return {
                "status": "completed",
                "phase": "completed",
                "result_index_path": self.artifacts.write_json("result_index.json", result),
            }

        return _node

    @staticmethod
    def route_after_review(state: GraphPipelineState) -> str:
        return "waiting" if state.get("needs_confirmation") else "continue"

    def _logger(self, state: GraphPipelineState) -> LegacyStageLoggerAdapter:
        task_id = state.get("task_id") or f"lg_{state['module_id']}"
        if task_id not in self._loggers:
            self._loggers[task_id] = LegacyStageLoggerAdapter(task_id)
        return self._loggers[task_id]

    @staticmethod
    def _read_text(path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    @staticmethod
    def _read_json(path: str) -> Any:
        return json.loads(Path(path).read_text(encoding="utf-8"))
