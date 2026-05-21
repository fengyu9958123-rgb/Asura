"""LangGraph testcase subgraph nodes reusing the legacy structured pipeline logic."""

from __future__ import annotations

import os
import time
from functools import wraps
from typing import Any, Callable, Dict

from agents.qa_agents.factory import QAAgentFactory
from services.generation.pipeline_artifact_service import PipelineArtifactService
from services.generation.llm_usage import UsageRecorder, usage_context
from services.generation.prd_document_cleaner import clean_prd_document
from services.generation.prd_block_service import (
    blocks_by_id,
    parse_prd_blocks,
    validate_block_plan,
    validate_prd_blocks,
)
from services.generation.prd_context_assembler import build_context_units_from_knowledge
from services.generation.prd_knowledge_service import knowledge_to_markdown, validate_prd_knowledge
from services.generation.structured_testcase_pipeline import StructuredTestcasePipeline

from .artifacts import TestcaseGraphArtifacts
from .state import TestcaseGraphState, public_state


class TestcaseGraphNodes:
    def __init__(
        self,
        output_dir: str,
        agents: Dict[str, Any] | None = None,
        progress_callback: Callable[[str, int, str], None] | None = None,
        usage_recorder: UsageRecorder | None = None,
    ):
        self.output_dir = output_dir
        self.artifacts = TestcaseGraphArtifacts(output_dir)
        self.pipeline = StructuredTestcasePipeline()
        self.pipeline_artifacts = PipelineArtifactService("langgraph_testcase_graph", base_dir=output_dir)
        self._agents: Dict[str, Any] | None = agents
        self.progress_callback = progress_callback
        self.usage_recorder = usage_recorder or UsageRecorder(output_dir)

    def _progress(self, stage: str, progress: int, message: str = "") -> None:
        if not self.progress_callback:
            return
        self.progress_callback(stage, progress, message)

    def node(self, node_name: str) -> Callable:
        def decorator(func: Callable[[TestcaseGraphState], Dict[str, Any]]) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
            @wraps(func)
            def wrapped(state: TestcaseGraphState) -> Dict[str, Any]:
                started = time.time()
                base_updates = {"current_node": node_name, "status": "running"}
                running_state = {**dict(state), **base_updates}
                result = self.artifacts.begin_result(node_name, running_state)
                self.artifacts.write_node_result(node_name, result)
                try:
                    updates = func(running_state) or {}
                    next_state = {**running_state, **updates}
                    self.artifacts.finalize_result(result, updates=updates, state=next_state, started=started)
                    return {**base_updates, **updates}
                except Exception as exc:
                    next_state = {**running_state, "status": "failed", "error": str(exc)}
                    self.artifacts.finalize_result(result, updates=None, state=next_state, started=started, error=exc)
                    raise

            return wrapped

        return decorator

    def prepare_agents(self) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
        @self.node("01_prepare_agents")
        def _node(state: TestcaseGraphState) -> Dict[str, Any]:
            self._ensure_agents()
            return {}

        return _node

    def block_prd(self) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
        @self.node("02_block_prd")
        def _node(state: TestcaseGraphState) -> Dict[str, Any]:
            self._progress("preparing_testcase_context", 66, "正在准备测试用例上下文...")
            agents = self._ensure_agents()
            final_prd = clean_prd_document(state["final_prd"]) or state["final_prd"]
            with usage_context(self.usage_recorder, "04a_prd_block_builder"):
                blocked_prd, block_plan, block_prompt, block_response, raw_block_plan = self.pipeline._generate_blocked_prd(
                    final_prd=final_prd,
                    task_name=state["task_name"],
                    agent=agents["prd_block_builder"],
                )
            prd_blocks = parse_prd_blocks(blocked_prd)
            block_validation = [
                *validate_block_plan(block_plan, final_prd),
                *validate_prd_blocks(prd_blocks, final_prd, blocked_prd),
            ]
            self.pipeline_artifacts.write_text("00_final_prd.md", final_prd, "final_prd")
            blocked_prd_path = self.pipeline_artifacts.write_text("04a_blocked_prd.md", blocked_prd, "blocked_prd_md")
            block_plan_path = self.pipeline_artifacts.write_json("04a_prd_block_plan.json", block_plan, "prd_block_plan_json")
            prd_blocks_path = self.pipeline_artifacts.write_json("04a_prd_blocks.json", {"blocks": prd_blocks}, "prd_blocks_json")
            self.pipeline_artifacts.write_text("prompts/04a_prd_block_builder.prompt.md", block_prompt, "prd_block_builder_prompt")
            self.pipeline_artifacts.write_text("responses/04a_prd_block_builder.response.md", block_response, "prd_block_builder_response")
            self.pipeline_artifacts.write_json("04a_prd_block_plan.raw.json", raw_block_plan, "prd_block_plan_raw_json")
            self.pipeline_artifacts.write_json("04a_block_validation.json", {"issues": block_validation}, "prd_block_validation")
            self.pipeline._raise_if_critical_issues(
                block_validation,
                "04a_prd_blocks",
                self.pipeline_artifacts,
                "PRD 分块存在关键问题",
            )
            return {
                "final_prd": final_prd,
                "blocked_prd": blocked_prd,
                "block_plan": block_plan,
                "prd_blocks": prd_blocks,
                "blocked_prd_path": blocked_prd_path,
                "block_plan_path": block_plan_path,
                "prd_blocks_path": prd_blocks_path,
            }

        return _node

    def build_knowledge(self) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
        @self.node("03_build_knowledge")
        def _node(state: TestcaseGraphState) -> Dict[str, Any]:
            self._progress("building_prd_knowledge", 70, "正在构建PRD知识结构...")
            agents = self._ensure_agents()
            blocked_prd = state.get("blocked_prd") or self._read_text(state["blocked_prd_path"])
            prd_blocks = state.get("prd_blocks") or self._read_json(state["prd_blocks_path"]).get("blocks", [])
            block_plan = state.get("block_plan") or self._read_json(state["block_plan_path"])
            block_validation = [
                *validate_block_plan(block_plan, state["final_prd"]),
                *validate_prd_blocks(prd_blocks, state["final_prd"], blocked_prd),
            ]
            with usage_context(self.usage_recorder, "04b_prd_knowledge_builder"):
                knowledge, knowledge_prompt, knowledge_response, raw_knowledge = self.pipeline._generate_prd_knowledge(
                    blocked_prd=blocked_prd,
                    prd_blocks=prd_blocks,
                    block_validation=block_validation,
                    agent=agents["prd_knowledge_builder"],
                )
            knowledge_validation = validate_prd_knowledge(knowledge, blocks_by_id(prd_blocks))
            knowledge_path = self.pipeline_artifacts.write_json("04b_prd_knowledge.json", knowledge, "prd_knowledge_json")
            self.pipeline_artifacts.write_text("04b_prd_knowledge.md", knowledge_to_markdown(knowledge), "prd_knowledge_md")
            self.pipeline_artifacts.write_text("prompts/04b_prd_knowledge_builder.prompt.md", knowledge_prompt, "prd_knowledge_builder_prompt")
            self.pipeline_artifacts.write_text("responses/04b_prd_knowledge_builder.response.md", knowledge_response, "prd_knowledge_builder_response")
            self.pipeline_artifacts.write_json("04b_prd_knowledge.raw.json", raw_knowledge, "prd_knowledge_raw_json")
            self.pipeline_artifacts.write_json("04b_prd_knowledge.validation.json", {"issues": knowledge_validation}, "prd_knowledge_validation")
            self.pipeline._raise_if_critical_issues(
                knowledge_validation,
                "04b_prd_knowledge",
                self.pipeline_artifacts,
                "PRD Knowledge 存在关键问题",
            )
            return {"knowledge": knowledge, "knowledge_path": knowledge_path}

        return _node

    def build_context_units(self) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
        @self.node("04_build_context_units")
        def _node(state: TestcaseGraphState) -> Dict[str, Any]:
            self._progress("building_testcase_units", 74, "正在组装用例生成单元...")
            knowledge = state.get("knowledge") or self._read_json(state["knowledge_path"])
            context_units = build_context_units_from_knowledge(knowledge)
            context_units_path = self.pipeline_artifacts.write_json("05_context_units.json", context_units, "context_units_json")
            self.pipeline_artifacts.write_text("05_context_units.md", self.pipeline._context_units_to_markdown(context_units), "context_units_md")
            return {"context_units": context_units, "context_units_path": context_units_path}

        return _node

    def generate_unit_cases(self) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
        @self.node("05_generate_unit_cases")
        def _node(state: TestcaseGraphState) -> Dict[str, Any]:
            agents = self._ensure_agents()
            knowledge = state.get("knowledge") or self._read_json(state["knowledge_path"])
            prd_blocks = state.get("prd_blocks") or self._read_json(state["prd_blocks_path"]).get("blocks", [])
            context_units = state.get("context_units") or self._read_json(state["context_units_path"])
            writer_agents = {
                "normal_lu": agents["module_test_case_writer"],
                "integration_lu": agents["integration_test_case_writer"],
            }
            total_units = len(context_units.get("context_units") or [])

            class ProgressProxy:
                def __init__(self, outer: "TestcaseGraphNodes"):
                    self.outer = outer

                def notify_log(self, _task_id: str, message: str) -> None:
                    if message.startswith("用例编写："):
                        return
                    self.outer._progress("generating_testcases", 76, message)

            artifacts = self.pipeline_artifacts
            original_write_json = artifacts.write_json
            progress_state = {"completed": 0}

            def write_json_with_progress(relative_path, payload, artifact_type):
                result = original_write_json(relative_path, payload, artifact_type)
                if str(relative_path).startswith("test_cases/") and str(relative_path).endswith(".cases.json"):
                    progress_state["completed"] += 1
                    completed = progress_state["completed"]
                    progress = 76 + int((completed / max(total_units, 1)) * 14)
                    self._progress(
                        "generating_testcases",
                        min(progress, 90),
                        f"正在生成测试用例：已完成 {completed}/{total_units} 个LU",
                    )
                return result

            artifacts.write_json = write_json_with_progress
            try:
                with usage_context(self.usage_recorder):
                    unit_results, _messages = self.pipeline._generate_cases_by_knowledge_context(
                        final_prd=state["final_prd"],
                        testing_notes=state.get("testing_notes") or "",
                        knowledge=knowledge,
                        prd_blocks_by_id=blocks_by_id(prd_blocks),
                        context_units=context_units,
                        writer_agents=writer_agents,
                        artifacts=self.pipeline_artifacts,
                        notification_service=ProgressProxy(self),
                        task_id=f"lg_{state['module_id']}",
                    )
            finally:
                artifacts.write_json = original_write_json
            unit_results_path = self.pipeline_artifacts.write_json("06_test_cases.by_unit.json", unit_results, "test_cases_by_unit_json")
            self.pipeline_artifacts.write_json("06_test_cases.by_package.json", unit_results, "test_cases_by_package_json")
            return {"unit_results": unit_results, "unit_results_path": unit_results_path}

        return _node

    def merge_cases(self) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
        @self.node("06_merge_cases")
        def _node(state: TestcaseGraphState) -> Dict[str, Any]:
            self._progress("merging_testcases", 92, "正在合并测试用例...")
            knowledge = state.get("knowledge") or self._read_json(state["knowledge_path"])
            context_units = state.get("context_units") or self._read_json(state["context_units_path"])
            unit_results = state.get("unit_results") or self._read_json(state["unit_results_path"])
            final_cases = self.pipeline._merge_unit_results(unit_results)
            if not final_cases:
                raise RuntimeError("PRD Knowledge 流水线完成但未生成任何测试用例")
            quality_review = {
                "enabled": False,
                "reason": "PRD Knowledge pipeline skips final testcase quality review; testcase quality is controlled by BLOCK/LU context generation.",
                "actions": [],
                "applied_actions": [],
                "skipped_actions": [],
                "issues": [],
            }
            self.pipeline_artifacts.write_json("07_test_cases.before_review.json", final_cases, "test_cases_before_review_json")
            self.pipeline_artifacts.write_text("07_test_cases.before_review.md", self.pipeline._cases_to_markdown(final_cases), "test_cases_before_review_md")
            self.pipeline_artifacts.write_json("07a_test_case_quality_review.json", quality_review, "test_case_quality_review_json")
            self.pipeline_artifacts.write_json("07a_test_cases.after_quality_review.json", final_cases, "test_cases_after_quality_review_json")
            self.pipeline_artifacts.write_text("07a_test_cases.after_quality_review.md", self.pipeline._cases_to_markdown(final_cases), "test_cases_after_quality_review_md")
            final_cases = self.pipeline._renumber_cases(final_cases)
            final_cases_md = self.pipeline._cases_to_markdown(final_cases)
            final_cases_path = self.pipeline_artifacts.write_json("07_test_cases.final.json", final_cases, "test_cases_final_json")
            final_cases_md_path = self.pipeline_artifacts.write_text("07_test_cases.final.md", final_cases_md, "test_cases_final_md")
            self.pipeline_artifacts.write_json("06_test_cases.final.json", final_cases, "test_cases_final_json_legacy")
            self.pipeline_artifacts.write_text("06_test_cases.final.md", final_cases_md, "test_cases_final_md_legacy")
            prd_blocks = state.get("prd_blocks") or self._read_json(state["prd_blocks_path"]).get("blocks", [])
            blocked_prd = state.get("blocked_prd") or self._read_text(state["blocked_prd_path"])
            block_plan = state.get("block_plan") or self._read_json(state["block_plan_path"])
            block_validation = [
                *validate_block_plan(block_plan, state["final_prd"]),
                *validate_prd_blocks(prd_blocks, state["final_prd"], blocked_prd),
            ]
            analysis = self.pipeline._build_prd_knowledge_pipeline_analysis(
                block_validation=block_validation,
                knowledge_validation=validate_prd_knowledge(knowledge, blocks_by_id(prd_blocks)),
                knowledge=knowledge,
                context_units=context_units,
                unit_results=unit_results,
                quality_review=quality_review,
            )
            analysis_path = self.pipeline_artifacts.write_text("08_test_analysis.md", analysis, "test_analysis_md")
            return {
                "final_cases": final_cases,
                "quality_review": quality_review,
                "final_cases_path": final_cases_path,
                "final_cases_md_path": final_cases_md_path,
                "analysis_path": analysis_path,
            }

        return _node

    def save_result(self) -> Callable[[TestcaseGraphState], Dict[str, Any]]:
        @self.node("07_save_result")
        def _node(state: TestcaseGraphState) -> Dict[str, Any]:
            self._progress("saving_results", 95, "正在保存测试用例结果...")
            final_cases = state.get("final_cases") or self._read_json(state["final_cases_path"])
            analysis_text = self._read_text(state["analysis_path"])
            final_cases_md = self._read_text(state["final_cases_md_path"])
            artifact_index_path = self.pipeline_artifacts.write_index()
            result = {
                "success": True,
                "pipeline_mode": "prd_knowledge_langgraph",
                "testcases": final_cases,
                "testcases_list": final_cases,
                "testcases_json": __import__("json").dumps(final_cases, ensure_ascii=False, indent=2),
                "testcases_raw": final_cases_md,
                "test_analysis": analysis_text,
                "analysis_prompt": "Prompts are saved under prompts/*.prompt.md",
                "testcase_prompt": "Unit testcase prompts are saved under prompts/test_cases/*.prompt.md",
                "artifact_dir": os.path.abspath(self.pipeline_artifacts.base_dir),
                "artifact_index": artifact_index_path,
                "artifacts": self.pipeline_artifacts.index,
                "usage_summary_path": str(self.usage_recorder.summary_path),
                "usage_records_path": str(self.usage_recorder.records_path),
                "usage_summary": self.usage_recorder.summarize(self.usage_recorder.read_records()),
            }
            test_results_path = self.artifacts.write_json("test_results.json", result)
            return {
                "artifact_index_path": artifact_index_path,
                "test_results": result,
                "test_results_path": test_results_path,
                "status": "completed",
            }

        return _node

    def _ensure_agents(self) -> Dict[str, Any]:
        if self._agents is not None:
            return self._agents
        from services.config.model_config_service import load_model_config

        config_list = load_model_config()
        factory = QAAgentFactory(config_list=config_list)
        self._agents = {
            "module_test_case_writer": factory.create_module_test_case_writer(),
            "integration_test_case_writer": factory.create_integration_test_case_writer(),
            "prd_block_builder": factory.create_prd_block_builder(),
            "prd_knowledge_builder": factory.create_prd_knowledge_builder(),
        }
        if not all(self._agents.values()):
            raise RuntimeError("创建 testcase LangGraph 所需智能体失败")
        return self._agents

    def _read_text(self, path: str) -> str:
        return open(path, "r", encoding="utf-8").read()

    def _read_json(self, path: str) -> Any:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
