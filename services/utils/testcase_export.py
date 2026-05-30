"""
测试用例导出工具：从数据库最新数据生成 Excel/JSON，并在保存后同步产物路径。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HIDDEN_TEST_CASE_COLUMNS = {
    "关联需求", "原始用例编号", "测试包ID", "测试包类型", "测试ID",
}


def public_test_cases(testcases: Any) -> Any:
    if not isinstance(testcases, list):
        return testcases
    public_cases = []
    for case in testcases:
        if not isinstance(case, dict):
            public_cases.append(case)
            continue
        public_cases.append({
            key: value
            for key, value in case.items()
            if key not in HIDDEN_TEST_CASE_COLUMNS
        })
    return public_cases


def build_export_file_info(
    file_service,
    testcases: List[dict],
    prd_name: str,
    task_id: str,
    file_type: str,
) -> Optional[Dict[str, Any]]:
    """根据最新测试用例生成 Excel 或 JSON 文件。"""
    if file_type not in ("excel", "json"):
        return None
    if not testcases:
        return None

    public_testcases = public_test_cases(testcases)
    safe_prd_name = prd_name or "PRD"
    safe_task_id = task_id or "task"

    if file_type == "excel":
        file_path = file_service.save_test_cases_to_excel(public_testcases, safe_prd_name, safe_task_id)
    else:
        output_dir = os.path.join(file_service.raw_folder, "json")
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f"testcases_{safe_prd_name}_{safe_task_id}.json")
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(public_testcases, handle, ensure_ascii=False, indent=2)

    if not file_path or not os.path.exists(file_path):
        return None

    return {
        "path": file_path,
        "name": os.path.basename(file_path),
        "size": os.path.getsize(file_path),
        "type": file_type,
    }


def load_export_context(session, identity, task_id: str) -> Tuple[Optional[List], Optional[str], str, Dict, Any]:
    """从数据库加载导出所需的测试用例、PRD 名称与 result_files。"""
    from database.models import RequirementModule, Task

    result_files: Dict[str, Any] = {}
    module = None

    if identity and identity.is_image and identity.module_id:
        module = session.query(RequirementModule).filter_by(id=identity.module_id).first()
        if not module:
            return None, None, task_id, {}, None
        testcases = None
        if module.test_cases_json:
            try:
                testcases = json.loads(module.test_cases_json)
            except json.JSONDecodeError:
                testcases = None
        if testcases is None:
            testcases = []
        prd_name = module.name or module.id
        effective_task_id = module.task_id or module.generated_task_id or module.id
        return testcases, prd_name, effective_task_id, result_files, module

    task = session.query(Task).filter_by(id=task_id).first()
    if not task:
        return None, None, task_id, {}, None

    testcases = task.testcases
    prd_name = task.name or task.prd_id or "PRD"
    result_files = task.result_files or {}
    if isinstance(result_files, str):
        try:
            result_files = json.loads(result_files)
        except json.JSONDecodeError:
            result_files = {}
    if not isinstance(result_files, dict):
        result_files = {}
    return testcases, prd_name, task_id, result_files, task


def build_fresh_export_from_db(file_service, task_id: str, file_type: str, identity=None) -> Optional[Dict[str, Any]]:
    """下载前：始终基于数据库最新测试用例重新生成导出文件。"""
    from database.models import db_manager
    from utils.task_identity import resolve_task_identity

    identity = identity or resolve_task_identity(task_id)
    canonical_task_id = identity.canonical_id or task_id

    session = db_manager.get_session()
    try:
        testcases, prd_name, effective_task_id, _, _ = load_export_context(session, identity, canonical_task_id)
        if not testcases:
            return None
        return build_export_file_info(file_service, testcases, prd_name, effective_task_id, file_type)
    finally:
        session.close()


def _normalize_result_files(result_files: Any) -> Dict[str, Any]:
    if isinstance(result_files, dict):
        return dict(result_files)
    if isinstance(result_files, str):
        try:
            parsed = json.loads(result_files)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _update_langgraph_test_results_file(result_files: Dict[str, Any], testcases: List[dict]) -> None:
    path = result_files.get("test_results_path")
    if not path:
        return
    file_path = Path(path)
    if not file_path.exists():
        return
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        payload["testcases"] = testcases
        payload["testcases_list"] = testcases
        if "test_cases" in payload:
            payload["test_cases"] = testcases
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("已同步 LangGraph test_results.json: %s", file_path)
    except Exception as exc:
        logger.warning("同步 test_results.json 失败: %s, error=%s", path, exc)


def sync_testcase_export_artifacts(
    file_service,
    task_manager,
    task_id: str,
    testcases: List[dict],
    identity=None,
) -> Optional[str]:
    """
    保存测试用例后：重新生成 Excel，更新 task.result_files / module.test_cases_file_path，
    并尽量同步 LangGraph 产物 JSON。
    """
    from datetime import datetime

    from database.models import RequirementModule, db_manager
    from utils.task_identity import resolve_task_identity

    identity = identity or resolve_task_identity(task_id)
    effective_task_id = identity.task_id or task_id

    session = db_manager.get_session()
    excel_path = None
    try:
        if identity.is_image and identity.module_id:
            module = session.query(RequirementModule).filter_by(id=identity.module_id).first()
            if not module:
                return None
            prd_name = module.name or module.id
            export_task_id = module.task_id or module.generated_task_id or module.id
            file_info = build_export_file_info(file_service, testcases, prd_name, export_task_id, "excel")
            if not file_info:
                session.commit()
                return None
            excel_path = file_info["path"]
            module.test_cases_file_path = excel_path
            module.updated_at = datetime.utcnow()
            session.commit()
            logger.info("图片任务 Excel 已重新生成: module=%s path=%s", identity.module_id, excel_path)
            return excel_path

        task = session.query(Task).filter_by(id=effective_task_id).first()
        if not task:
            return None

        prd_name = task.name or task.prd_id or "PRD"
        file_info = build_export_file_info(file_service, testcases, prd_name, effective_task_id, "excel")
        if not file_info:
            session.commit()
            return None

        excel_path = file_info["path"]
        result_files = _normalize_result_files(task.result_files)
        result_files["excel"] = excel_path
        task.result_files = result_files
        task.updated_at = datetime.utcnow()
        session.commit()

        _update_langgraph_test_results_file(result_files, testcases)

        if task_manager:
            task_manager.update_task(effective_task_id, result_files=result_files)

        logger.info("文本任务 Excel 已重新生成: task=%s path=%s", effective_task_id, excel_path)
        return excel_path
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
