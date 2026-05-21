"""Service entrypoint for the isolated LangGraph text PRD pipeline."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from database.models import DatabaseManager, PRD, Task, TaskStatus
from database.task_manager import SQLiteTaskManager

from .artifacts import TextGraphArtifacts, graph_output_dir
from .graph import build_graph
from .nodes import TextGraphPipelineNodes
from .state import TextGraphPipelineState


class LangGraphTextPipelineService:
    """Run the isolated LangGraph text PRD pipeline."""

    def run(
        self,
        prd_id: str,
        task_id: str,
        progress_callback=None,
    ) -> Dict[str, Any]:
        output_dir = graph_output_dir(str(task_id))
        nodes = TextGraphPipelineNodes(output_dir, progress_callback=progress_callback)
        graph = build_graph(nodes, resume=False)
        state: TextGraphPipelineState = {
            "prd_id": str(prd_id),
            "task_id": str(task_id),
            "output_dir": output_dir,
            "phase": "pre_confirmation",
            "status": "running",
        }
        result = graph.invoke(state)
        TextGraphArtifacts(output_dir).write_state(result)
        return dict(result)

    def resume(
        self,
        task_id: str,
        answers_path: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        output_dir = graph_output_dir(str(task_id))
        artifacts = TextGraphArtifacts(output_dir)
        state_path = Path(output_dir) / "graph_state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"text graph state not found: {state_path}")
        state: TextGraphPipelineState = json.loads(state_path.read_text(encoding="utf-8"))
        answers_file = Path(answers_path) if answers_path else Path(output_dir) / "confirmation" / "answers.json"
        if not answers_file.exists() and state.get("needs_confirmation"):
            raise FileNotFoundError(f"confirmation answers not found: {answers_file}")
        if answers_file.exists():
            state["confirmation_answers_path"] = str(answers_file)
            state["confirmation_answers"] = json.loads(answers_file.read_text(encoding="utf-8"))
        state["status"] = "running"
        state["phase"] = "post_confirmation"
        nodes = TextGraphPipelineNodes(output_dir, progress_callback=progress_callback)
        graph = build_graph(nodes, resume=True)
        result = graph.invoke(state)
        artifacts.write_state(result)
        return dict(result)


class LangGraphTextPipelineRuntimeService:
    """DB-backed runtime adapter for text PRD LangGraph generation."""

    def __init__(self):
        self.db_manager = DatabaseManager()
        self.db_manager.initialize()
        self.task_manager = SQLiteTaskManager()

    def start_generation(self, prd_id: str) -> Dict[str, Any]:
        prd = self._get_prd(prd_id)
        if prd.status == "processing" and prd.generated_task_id:
            task = self._get_task_or_none(prd.generated_task_id)
            if task and self._task_status_value(task) in {"processing", "running", "waiting_confirmation"}:
                raise ValueError("任务正在处理中，请勿重复启动")

        task_id = self.task_manager.create_task(
            prd_id=prd.id,
            prd_name=prd.name,
            prd_content=prd.content,
            mode=None,
            business=prd.business,
        )
        self._update_prd(prd.id, status="processing", generated_task_id=task_id)
        self.task_manager.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            completion_percentage=0,
            message="文本PRD任务已启动（LangGraph）",
            current_phase="initializing",
            result_files={
                "pipeline": "text_langgraph",
                "output_dir": graph_output_dir(task_id),
            },
        )
        thread = threading.Thread(
            target=self._run_background,
            args=(prd.id, task_id),
            daemon=True,
        )
        thread.start()
        return {
            "task_id": task_id,
            "prd_id": prd.id,
            "status": "processing",
            "message": "文本PRD任务启动成功（LangGraph）",
        }

    def continue_after_confirmation(self, task_id: str, answers: Dict[str, str]) -> None:
        task = self._get_task(task_id)
        output_dir = graph_output_dir(task_id)
        normalized_answers = self._normalize_answers(task.confirmation_items or [], answers or {})
        answers_path = Path(output_dir) / "confirmation" / "answers.json"
        answers_path.parent.mkdir(parents=True, exist_ok=True)
        answers_path.write_text(json.dumps(normalized_answers, ensure_ascii=False, indent=2), encoding="utf-8")
        confirmation_results = self._build_confirmation_results(task.confirmation_items or [], normalized_answers)
        self.task_manager.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            completion_percentage=50,
            message="已收到人工确认，继续生成最终PRD",
            confirmation_results=json.dumps(confirmation_results, ensure_ascii=False),
            current_phase="final_prd_integrate",
            result_files={
                **(task.result_files or {}),
                "pipeline": "text_langgraph",
                "output_dir": output_dir,
            },
        )
        thread = threading.Thread(
            target=self._resume_background,
            args=(task_id, str(answers_path)),
            daemon=True,
        )
        thread.start()

    def _run_background(self, prd_id: str, task_id: str) -> None:
        try:
            result = LangGraphTextPipelineService().run(
                prd_id,
                task_id,
                progress_callback=lambda stage, progress, message="": self._sync_progress(task_id, stage, progress, message),
            )
            if result.get("status") == "waiting_confirmation":
                self._sync_waiting_confirmation(task_id, result)
                return
            self._sync_completed(task_id, result)
        except Exception as exc:
            self._mark_failed(task_id, str(exc))

    def _resume_background(self, task_id: str, answers_path: str) -> None:
        try:
            result = LangGraphTextPipelineService().resume(
                task_id,
                answers_path=answers_path,
                progress_callback=lambda stage, progress, message="": self._sync_progress(task_id, stage, progress, message),
            )
            self._sync_completed(task_id, result)
        except Exception as exc:
            self._mark_failed(task_id, str(exc))

    def _sync_progress(self, task_id: str, stage: str, progress: int, message: str = "") -> None:
        self.task_manager.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            completion_percentage=progress,
            message=message or stage,
            current_phase=stage,
        )

    def _sync_waiting_confirmation(self, task_id: str, state: Dict[str, Any]) -> None:
        questions = self._read_json_path(state.get("confirmation_items_path"), default=[])
        self.task_manager.update_task(
            task_id,
            status=TaskStatus.WAITING_CONFIRMATION,
            completion_percentage=45,
            message="等待人工确认",
            confirmation_items=questions,
            current_phase="waiting_confirmation",
            result_files={
                "pipeline": "text_langgraph",
                "output_dir": state.get("output_dir"),
                "graph_state": str(Path(state.get("output_dir", "")) / "graph_state.json") if state.get("output_dir") else "",
            },
        )

    def _sync_completed(self, task_id: str, state: Dict[str, Any]) -> None:
        final_prd = self._read_text_path(state.get("final_prd_path"))
        test_results = state.get("test_results") if isinstance(state.get("test_results"), dict) else {}
        if not test_results:
            test_results = self._read_json_path(state.get("test_results_path"), default={})
        if not test_results:
            fallback = Path(state.get("output_dir", "")) / "testcase_pipeline" / "test_results.json"
            test_results = self._read_json_path(str(fallback), default={})
        testcases = test_results.get("testcases_list") or test_results.get("testcases") or []
        self.task_manager.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            completion_percentage=100,
            message=f"文本PRD任务完成，共生成{len(testcases)}个测试用例",
            final_prd=final_prd,
            testcases=testcases,
            test_analysis=test_results.get("test_analysis", ""),
            test_case_writer_messages=json.dumps(self._collect_testcase_messages(state.get("output_dir")), ensure_ascii=False),
            current_phase="completed",
            result_files={
                "pipeline": "text_langgraph",
                "output_dir": state.get("output_dir"),
                "result_index": state.get("result_index_path"),
                "artifact_dir": test_results.get("artifact_dir") or state.get("testcase_artifact_dir"),
                "artifact_index": test_results.get("artifact_index") or state.get("testcase_artifact_index"),
                "final_prd_path": state.get("final_prd_path"),
                "test_results_path": state.get("test_results_path"),
            },
        )

    def _mark_failed(self, task_id: str, error: str) -> None:
        self.task_manager.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=error,
            current_phase="failed",
        )

    def _get_prd(self, prd_id: str) -> PRD:
        session = self.db_manager.get_session()
        try:
            prd = session.query(PRD).filter_by(id=str(prd_id)).first()
            if not prd:
                raise ValueError(f"PRD不存在: {prd_id}")
            session.expunge(prd)
            return prd
        finally:
            session.close()

    def _get_task(self, task_id: str) -> Task:
        task = self._get_task_or_none(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")
        return task

    def _get_task_or_none(self, task_id: str) -> Optional[Task]:
        session = self.db_manager.get_session()
        try:
            task = session.query(Task).filter_by(id=str(task_id)).first()
            if task:
                session.expunge(task)
            return task
        finally:
            session.close()

    def _update_prd(self, prd_id: str, **kwargs: Any) -> None:
        session = self.db_manager.get_session()
        try:
            prd = session.query(PRD).filter_by(id=str(prd_id)).first()
            if not prd:
                raise ValueError(f"PRD不存在: {prd_id}")
            for key, value in kwargs.items():
                setattr(prd, key, value)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _task_status_value(task: Task) -> str:
        return task.status.value if hasattr(task.status, "value") else str(task.status)

    @staticmethod
    def _normalize_answers(questions: Any, answers: Dict[str, str]) -> Dict[str, str]:
        normalized: Dict[str, str] = {}
        question_list = questions if isinstance(questions, list) else []
        for index, item in enumerate(question_list):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or item.get("number") or f"Q{index + 1:03d}")
            value = (
                answers.get(item_id)
                or answers.get(f"answer_{index}")
                or answers.get(str(index))
                or answers.get(f"answer_{item_id}")
                or ""
            )
            normalized[item_id] = value
        for key, value in answers.items():
            if key not in normalized and not str(key).startswith("answer_"):
                normalized[str(key)] = value
        return normalized

    @staticmethod
    def _build_confirmation_results(questions: Any, answers: Dict[str, str]) -> list:
        results = []
        question_list = questions if isinstance(questions, list) else []
        for index, item in enumerate(question_list):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or item.get("number") or f"Q{index + 1:03d}")
            results.append({
                "confirmation_id": item_id,
                "user_answer": answers.get(item_id, ""),
                "confirmed": True,
                "question_details": item.get("question_details") or item.get("description") or item.get("question") or "",
            })
        return results

    @staticmethod
    def _collect_testcase_messages(output_dir: Optional[str]) -> list:
        if not output_dir:
            return []
        base = Path(output_dir) / "testcase_pipeline"
        messages = []
        for prompt_path in sorted((base / "prompts").glob("*.prompt.md")) if (base / "prompts").exists() else []:
            messages.append({"role": "user", "content": prompt_path.read_text(encoding="utf-8")})
            response_path = base / "responses" / prompt_path.name.replace(".prompt.md", ".response.md")
            if response_path.exists():
                messages.append({"role": "assistant", "content": response_path.read_text(encoding="utf-8")})
        prompt_dir = base / "prompts" / "test_cases"
        response_dir = base / "responses" / "test_cases"
        for prompt_path in sorted(prompt_dir.glob("*.prompt.md")) if prompt_dir.exists() else []:
            messages.append({"role": "user", "content": prompt_path.read_text(encoding="utf-8")})
            response_path = response_dir / prompt_path.name.replace(".prompt.md", ".response.md")
            if response_path.exists():
                messages.append({"role": "assistant", "content": response_path.read_text(encoding="utf-8")})
        return messages

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
