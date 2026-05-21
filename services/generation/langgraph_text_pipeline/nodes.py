"""LangGraph nodes for the isolated text PRD pipeline."""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List

from agents.qa_agents.factory import QAAgentFactory
from database.models import PRD, Task, db_manager
from services.generation.image_prd_core import extract_confirmation_items
from services.generation.llm_usage import UsageRecorder, usage_context
from services.generation.prd_document_cleaner import clean_prd_document
from services.generation.structured_testcase_pipeline import StructuredTestcasePipeline
from services.generation.langgraph_pipeline.testcase_graph import (
    TestcaseGraphNodes,
    build_graph as build_testcase_graph,
)

from .artifacts import TextGraphArtifacts
from .state import TextGraphPipelineState, public_state


class TextGraphPipelineNodes:
    def __init__(
        self,
        output_dir: str,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ):
        self.artifacts = TextGraphArtifacts(output_dir)
        self.progress_callback = progress_callback
        self._agents: Dict[str, Any] | None = None
        self._agent_caller = StructuredTestcasePipeline()
        self.usage_recorder = UsageRecorder(output_dir)

    def _progress(self, stage: str, progress: int, message: str = "") -> None:
        if self.progress_callback:
            self.progress_callback(stage, progress, message)

    def node(self, node_name: str) -> Callable:
        def decorator(func: Callable[[TextGraphPipelineState], Dict[str, Any]]) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
            @wraps(func)
            def wrapped(state: TextGraphPipelineState) -> Dict[str, Any]:
                started = time.time()
                base_updates = {"current_node": node_name, "status": "running"}
                running_state = {**dict(state), **base_updates}
                record = self.artifacts.begin_node_record(node_name, running_state)
                self.artifacts.write_node_result(node_name, record)
                try:
                    updates = func(running_state) or {}
                    next_state = {**running_state, **updates}
                    record["status"] = "success"
                    record["updates"] = public_state(updates)
                    return {**base_updates, **updates}
                except Exception as exc:
                    next_state = {**running_state, "status": "failed", "error": str(exc)}
                    record["status"] = "failed"
                    record["error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    raise
                finally:
                    record["finished_at"] = datetime.now().isoformat()
                    record["duration_ms"] = int((time.time() - started) * 1000)
                    record["output_state"] = public_state(next_state)
                    self.artifacts.write_node_result(node_name, record)
                    self.artifacts.write_state(next_state)

            return wrapped

        return decorator

    def load_prd(self) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
        @self.node("01_load_prd")
        def _node(state: TextGraphPipelineState) -> Dict[str, Any]:
            prd = self._get_prd(state["prd_id"])
            task = self._get_task(state["task_id"])
            original_prd = str(task.prd_content or prd.content or "")
            self.artifacts.write_json("task.json", self._task_to_dict(task))
            self.artifacts.write_json("prd.json", prd.to_dict())
            original_prd_path = self.artifacts.write_text("prd/00_original_prd.md", original_prd)
            return {
                "task_name": task.name or prd.name,
                "business": task.business or prd.business or "",
                "original_prd": original_prd,
                "original_prd_path": original_prd_path,
                "output_dir": str(self.artifacts.output_dir),
                "phase": state.get("phase") or "pre_confirmation",
            }

        return _node

    def clean_prd(self) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
        @self.node("02_clean_prd")
        def _node(state: TextGraphPipelineState) -> Dict[str, Any]:
            self._progress("cleaning_prd", 15, "正在整理原始PRD...")
            original_prd = state.get("original_prd") or self._read_text(state["original_prd_path"])
            cleaned_prd = clean_prd_document(original_prd) or original_prd
            return {
                "cleaned_prd": cleaned_prd,
                "cleaned_prd_path": self.artifacts.write_text("prd/01_cleaned_prd.md", cleaned_prd),
            }

        return _node

    def prd_logic_review(self) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
        @self.node("03_prd_logic_review")
        def _node(state: TextGraphPipelineState) -> Dict[str, Any]:
            self._progress("reviewing_prd", 35, "正在审查PRD逻辑闭环...")
            agents = self._ensure_agents()
            cleaned_prd = state.get("cleaned_prd") or self._read_text(state["cleaned_prd_path"])
            prompt = self._build_review_prompt(state, cleaned_prd)
            with usage_context(self.usage_recorder, "03_text_prd_logic_review"):
                response = self._agent_caller._call_agent(agents["text_prd_logic_reviewer"], prompt)
            review_result = self._parse_review_result(response)
            questions = self._normalize_confirmation_items(review_result.get("questions") or [])
            self.artifacts.write_text("prompts/03_text_prd_logic_reviewer.prompt.md", prompt)
            self.artifacts.write_text("responses/03_text_prd_logic_reviewer.response.md", response)
            return {
                "review_result": review_result,
                "review_result_path": self.artifacts.write_json("prd/02_logic_review.json", review_result),
                "confirmation_items": questions,
                "confirmation_items_path": self.artifacts.write_json("confirmation/items.json", questions),
                "needs_confirmation": bool(questions),
            }

        return _node

    def wait_for_confirmation(self) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
        @self.node("04_waiting_confirmation")
        def _node(state: TextGraphPipelineState) -> Dict[str, Any]:
            self._progress("waiting_confirmation", 45, "等待人工确认...")
            return {
                "phase": "waiting_confirmation",
                "status": "waiting_confirmation",
            }

        return _node

    def final_prd_integrate(self) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
        @self.node("05_final_prd_integrate")
        def _node(state: TextGraphPipelineState) -> Dict[str, Any]:
            self._progress("finalizing_prd", 55, "正在生成最终PRD...")
            agents = self._ensure_agents()
            cleaned_prd = (
                state.get("cleaned_prd")
                or self._read_text_if_exists(state.get("cleaned_prd_path"))
                or clean_prd_document(state.get("original_prd") or self._read_text(state["original_prd_path"]))
            )
            questions = state.get("confirmation_items")
            if questions is None and state.get("confirmation_items_path"):
                questions = self._read_json(state["confirmation_items_path"])
            answers = state.get("confirmation_answers")
            if answers is None and state.get("confirmation_answers_path"):
                answers = self._read_json(state["confirmation_answers_path"])
            prompt = self._build_integrate_prompt(cleaned_prd, questions or [], answers or {})
            with usage_context(self.usage_recorder, "05_text_final_prd_integrate"):
                response = self._agent_caller._call_agent(agents["text_final_prd_integrator"], prompt)
            final_prd = clean_prd_document(response) or response
            self.artifacts.write_text("prompts/05_text_final_prd_integrator.prompt.md", prompt)
            self.artifacts.write_text("responses/05_text_final_prd_integrator.response.md", response)
            return {
                "final_prd": final_prd,
                "final_prd_path": self.artifacts.write_text("prd/03_final_prd.md", final_prd),
                "phase": "post_confirmation",
            }

        return _node

    def testcase_pipeline(self) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
        @self.node("06_testcase_pipeline")
        def _node(state: TextGraphPipelineState) -> Dict[str, Any]:
            self._progress("generating_testcases", 65, "正在生成测试用例...")
            final_prd = state.get("final_prd") or self._read_text(state["final_prd_path"])
            testcase_output_dir = str(Path(self.artifacts.output_dir) / "testcase_pipeline")
            testcase_nodes = TestcaseGraphNodes(
                testcase_output_dir,
                progress_callback=self.progress_callback,
                usage_recorder=self.usage_recorder,
            )
            testcase_graph = build_testcase_graph(testcase_nodes)
            testcase_state = {
                "module_id": state["task_id"],
                "task_name": state.get("task_name") or state["task_id"],
                "final_prd": final_prd,
                "testing_notes": "",
                "output_dir": testcase_output_dir,
                "status": "running",
            }
            testcase_result_state = testcase_graph.invoke(testcase_state)
            test_results = testcase_result_state.get("test_results") or {}
            return {
                "test_results": test_results,
                "test_results_path": testcase_result_state.get("test_results_path", ""),
                "testcase_artifact_dir": test_results.get("artifact_dir", ""),
                "testcase_artifact_index": test_results.get("artifact_index", ""),
            }

        return _node

    def save_result(self) -> Callable[[TextGraphPipelineState], Dict[str, Any]]:
        @self.node("07_save_result")
        def _node(state: TextGraphPipelineState) -> Dict[str, Any]:
            self._progress("saving_results", 95, "正在保存结果...")
            test_results = state.get("test_results") or {}
            result = {
                "task_id": state.get("task_id"),
                "prd_id": state.get("prd_id"),
                "task_name": state.get("task_name"),
                "status": "completed",
                "final_prd_path": state.get("final_prd_path"),
                "testcases_count": len(test_results.get("testcases_list") or []),
                "artifact_dir": test_results.get("artifact_dir"),
                "artifact_index": test_results.get("artifact_index"),
                "usage_summary_path": str(self.usage_recorder.summary_path),
                "usage_records_path": str(self.usage_recorder.records_path),
                "usage_summary": self.usage_recorder.summarize(self.usage_recorder.read_records()),
            }
            return {
                "status": "completed",
                "phase": "completed",
                "result_index_path": self.artifacts.write_json("result_index.json", result),
            }

        return _node

    @staticmethod
    def route_after_review(state: TextGraphPipelineState) -> str:
        return "waiting" if state.get("needs_confirmation") else "continue"

    def _ensure_agents(self) -> Dict[str, Any]:
        if self._agents is not None:
            return self._agents
        from services.config.model_config_service import load_model_config

        config_list = load_model_config()
        factory = QAAgentFactory(config_list=config_list)
        self._agents = {
            "text_prd_logic_reviewer": factory.create_text_prd_logic_reviewer(),
            "text_final_prd_integrator": factory.create_text_final_prd_integrator(),
        }
        if not all(self._agents.values()):
            raise RuntimeError("创建文本 LangGraph 所需智能体失败")
        return self._agents

    def _build_review_prompt(self, state: TextGraphPipelineState, cleaned_prd: str) -> str:
        return f"""请审查以下文本 PRD 是否存在需要人工确认的逻辑不闭环、歧义或关键缺失。

任务名称：{state.get("task_name") or ""}
业务类型：{state.get("business") or ""}

【原始 PRD】
{cleaned_prd}
"""

    def _build_integrate_prompt(
        self,
        cleaned_prd: str,
        questions: List[Dict[str, Any]],
        answers: Dict[str, str],
    ) -> str:
        confirmation_text = self._format_confirmation_for_prompt(questions, answers)
        return f"""请基于原始 PRD 和人工确认结果，生成最终 PRD。

【原始 PRD】
{cleaned_prd}

【人工确认结果】
{confirmation_text}
"""

    def _parse_review_result(self, response: str) -> Dict[str, Any]:
        text = str(response or "").strip()
        if not text or text in {"无", "无。", "没有", "没有。"}:
            return {"has_questions": False, "questions": []}
        questions = extract_confirmation_items(text)
        if not questions and "<HUMAN_CONFIRM_START>" in text:
            self.artifacts.write_text("responses/03_text_prd_logic_reviewer.invalid.md", response)
            raise ValueError("TextPRDLogicReviewer returned malformed HUMAN_CONFIRM blocks")
        if not questions:
            self.artifacts.write_text("responses/03_text_prd_logic_reviewer.invalid.md", response)
            raise ValueError("TextPRDLogicReviewer must output HUMAN_CONFIRM blocks or '无'")
        return {
            "has_questions": bool(questions),
            "questions": questions,
            "raw_response": response,
        }

    @staticmethod
    def _normalize_confirmation_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for index, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or item.get("number") or f"Q{index:03d}")
            question = str(item.get("question") or item.get("title") or f"确认项{index}")
            title = question
            description = str(item.get("description") or title)
            item_format_type = str(item.get("format_type") or "").strip()
            reference_examples = item.get("reference_examples") or item.get("examples") or []
            if not reference_examples and item_format_type == "open":
                reference_examples = item.get("options") or []
            if isinstance(reference_examples, str):
                reference_examples = [reference_examples]
            normalized.append({
                "id": item_id,
                "number": item_id,
                "title": title,
                "question": question,
                "description": description,
                "reference_examples": reference_examples,
                "options": [],
                "confirm_points": [],
                "format_type": "open",
                "question_details": TextGraphPipelineNodes._question_details(
                    question,
                    description,
                    reference_examples=reference_examples,
                ),
            })
        return normalized

    @staticmethod
    def _question_details(
        question: str,
        description: str,
        reference_examples: List[str] | None = None,
    ) -> str:
        details = f"**{question}**\n\n{description}"
        if reference_examples:
            details += "\n\n**参考示例：**\n"
            for example in reference_examples:
                details += f"- {example}\n"
        return details

    @staticmethod
    def _format_confirmation_for_prompt(questions: List[Dict[str, Any]], answers: Dict[str, str]) -> str:
        if not questions:
            return "无人工确认项。"
        lines = []
        for index, item in enumerate(questions, start=1):
            item_id = str(item.get("id") or item.get("number") or f"Q{index:03d}")
            answer = (
                answers.get(item_id)
                or answers.get(f"answer_{index - 1}")
                or answers.get(str(index - 1))
                or ""
            )
            lines.append(
                "\n".join([
                    f"## {item_id} {item.get('title') or item.get('question') or ''}",
                    f"问题：{item.get('question') or ''}",
                    f"原文依据：{item.get('source_evidence') or ''}",
                    f"人工确认答案：{answer}",
                ])
            )
        return "\n\n".join(lines)

    @staticmethod
    def _get_prd(prd_id: str) -> PRD:
        session = db_manager.get_session()
        try:
            prd = session.query(PRD).filter_by(id=prd_id).first()
            if not prd:
                raise ValueError(f"PRD不存在: {prd_id}")
            session.expunge(prd)
            return prd
        finally:
            session.close()

    @staticmethod
    def _get_task(task_id: str) -> Task:
        session = db_manager.get_session()
        try:
            task = session.query(Task).filter_by(id=task_id).first()
            if not task:
                raise ValueError(f"任务不存在: {task_id}")
            session.expunge(task)
            return task
        finally:
            session.close()

    @staticmethod
    def _task_to_dict(task: Task) -> Dict[str, Any]:
        status = task.status.value if hasattr(task.status, "value") else str(task.status)
        return {
            "id": task.id,
            "prd_id": task.prd_id,
            "name": task.name,
            "status": status,
            "business": task.business,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }

    @staticmethod
    def _read_text(path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    @staticmethod
    def _read_text_if_exists(path: str | None) -> str:
        if not path:
            return ""
        file_path = Path(path)
        return file_path.read_text(encoding="utf-8") if file_path.exists() else ""

    @staticmethod
    def _read_json(path: str) -> Any:
        return json.loads(Path(path).read_text(encoding="utf-8"))
