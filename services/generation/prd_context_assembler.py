"""
Assemble compact testcase-generation contexts from PRD Knowledge LU groups.
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_context_units_from_knowledge(knowledge: Dict[str, Any]) -> Dict[str, Any]:
    units: List[Dict[str, Any]] = []
    for module in knowledge.get("modules") or []:
        unit_id = str(module.get("lu_id") or "")
        if not unit_id:
            continue
        primary_block_ids = module.get("primary_block_ids") or module.get("block_ids") or []
        support_block_ids = module.get("support_block_ids") or []
        units.append({
            "unit_id": unit_id,
            "unit_name": module.get("title") or unit_id,
            "unit_type": "normal_lu",
            "source_type": "prd_knowledge_normal_lu",
            "source_id": unit_id,
            "requirement_ids": primary_block_ids,
            "supporting_requirement_ids": support_block_ids,
            "source_claim_ids": [],
            "related_module_ids": [],
            "dependencies": [],
            "flow_hint": "",
            "flow_outline": [],
            "excluded_atomic_focus": [],
            "evidence_block_ids": _dedupe([*primary_block_ids, *support_block_ids]),
            "unit_boundary": module.get("summary") or "",
        })
    for module in knowledge.get("integration_modules") or []:
        unit_id = str(module.get("lu_id") or "")
        if not unit_id:
            continue
        evidence_block_ids = module.get("evidence_block_ids") or module.get("primary_block_ids") or module.get("block_ids") or []
        support_block_ids = module.get("support_block_ids") or []
        units.append({
            "unit_id": unit_id,
            "unit_name": module.get("title") or unit_id,
            "unit_type": "integration_lu",
            "source_type": "prd_knowledge_integration_lu",
            "source_id": unit_id,
            "covered_lu_ids": module.get("covered_lu_ids") or [],
            "requirement_ids": evidence_block_ids,
            "supporting_requirement_ids": support_block_ids,
            "source_claim_ids": [],
            "related_module_ids": module.get("covered_lu_ids") or [],
            "dependencies": module.get("covered_lu_ids") or [],
            "flow_hint": module.get("flow_hint") or module.get("integration_focus") or module.get("summary") or "",
            "flow_outline": module.get("flow_outline") or [],
            "excluded_atomic_focus": module.get("excluded_atomic_focus") or [],
            "evidence_block_ids": _dedupe([*evidence_block_ids, *support_block_ids]),
            "unit_boundary": module.get("flow_hint") or module.get("integration_focus") or module.get("summary") or "",
        })
    return {
        "unit_summary": "PRD Knowledge 将 normal_lu 映射为普通用例生成单元，将 integration_lu 映射为跨模块链路用例生成单元；normal_lu 回填主需求 BLOCK，integration_lu 回填链路证据 BLOCK 与 flow_hint/flow_outline；support_only_blocks 默认不进入写用例上下文。",
        "context_units": units,
    }


def assemble_context_for_module(
    module: Dict[str, Any],
    knowledge: Dict[str, Any],
    blocks_by_id: Dict[str, Dict[str, Any]],
    final_prd: str,
) -> Dict[str, Any]:
    unit_type = module.get("unit_type") or "normal_lu"
    if unit_type == "integration_lu":
        main_block_ids = _dedupe([
            block_id
            for block_id in (module.get("evidence_block_ids") or module.get("primary_block_ids") or module.get("block_ids") or [])
            if block_id in blocks_by_id
        ])
    else:
        main_block_ids = _dedupe([
            block_id
            for block_id in (module.get("primary_block_ids") or module.get("block_ids") or [])
            if block_id in blocks_by_id
        ])
    support_block_ids = _dedupe([
        block_id
        for block_id in module.get("support_block_ids") or []
        if block_id in blocks_by_id and block_id not in main_block_ids
    ])
    primary_blocks = _build_block_context(main_block_ids, blocks_by_id, final_prd)
    support_blocks = _build_block_context(support_block_ids, blocks_by_id, final_prd)

    assembled = {
        "unit_id": module.get("lu_id"),
        "unit_name": module.get("title") or module.get("lu_id"),
        "unit_type": unit_type,
        "global_summary": knowledge.get("global_summary") or knowledge.get("global_kernel") or "",
        "global_kernel": knowledge.get("global_summary") or knowledge.get("global_kernel") or "",
        "module": _compact_module(module),
        "primary_blocks": primary_blocks,
        "support_blocks": support_blocks,
        "global_blocks": [],
        "requirement_ids": main_block_ids,
        "supporting_requirement_ids": support_block_ids,
        "evidence_block_ids": _dedupe([*main_block_ids, *support_block_ids]),
        "flow_hint": module.get("flow_hint") or module.get("integration_focus") or "",
        "flow_outline": module.get("flow_outline") or [],
        "excluded_atomic_focus": module.get("excluded_atomic_focus") or [],
        "support_only_blocks": knowledge.get("support_only_blocks") or [],
    }
    assembled["local_requirement_doc_md"] = context_to_markdown(assembled)
    return assembled


def context_to_markdown(context: Dict[str, Any]) -> str:
    lines: List[str] = ["# 用例生成上下文", ""]
    if context.get("global_summary") or context.get("global_kernel"):
        lines.append("## 全局需求认知")
        lines.append(str(context.get("global_summary") or context.get("global_kernel")))
        lines.append("")
    module = context.get("module") or {}
    unit_type = module.get("unit_type", context.get("unit_type", "normal_lu"))
    is_integration = unit_type == "integration_lu"
    lines.append("## 当前 LU")
    lines.append(f"- ID: {module.get('lu_id', '')}")
    lines.append(f"- 类型: {unit_type}")
    lines.append(f"- 标题: {module.get('title', '')}")
    lines.append(f"- 摘要: {module.get('summary', '')}")
    if module.get("covered_lu_ids"):
        lines.append(f"- 覆盖普通 LU: {', '.join(module.get('covered_lu_ids') or [])}")
    flow_hint = module.get("flow_hint") or module.get("integration_focus") or context.get("flow_hint") or ""
    if flow_hint:
        lines.append(f"- 链路目标: {flow_hint}")
    flow_outline = module.get("flow_outline") or context.get("flow_outline") or []
    if flow_outline:
        lines.append(f"- 链路骨架: {' -> '.join(flow_outline)}")
    excluded_atomic_focus = module.get("excluded_atomic_focus") or context.get("excluded_atomic_focus") or []
    if excluded_atomic_focus:
        lines.append(f"- 排除单点: {'；'.join(excluded_atomic_focus)}")
    block_label = "链路证据 BLOCK" if is_integration else "主需求 BLOCK"
    lines.append(f"- {block_label}: {', '.join(module.get('evidence_block_ids') or module.get('primary_block_ids') or module.get('block_ids') or [])}")
    lines.append(f"- 辅助证据 BLOCK: {', '.join(module.get('support_block_ids') or []) or '无'}")
    lines.append("")
    lines.append("## 当前 LU 链路证据 BLOCK" if is_integration else "## 当前 LU 主需求 BLOCK")
    if is_integration:
        lines.append("以下 BLOCK 共同支撑这条链路，用例应围绕流程、联动、状态传递和一致性展开，不要把单点原子事实拆成独立功能用例。")
    else:
        lines.append("以下 BLOCK 可以驱动独立测试用例。")
    lines.append("")
    for block in context.get("primary_blocks") or []:
        lines.append(_block_context_to_markdown(block))
        lines.append("")
    if context.get("support_blocks"):
        lines.append("## 当前 LU 辅助证据 BLOCK")
        lines.append("以下 BLOCK 只能补充字段、枚举、提示文案、状态、边界或流程上下文，不能单独生成用例。")
        lines.append("")
        for block in context.get("support_blocks") or []:
            lines.append(_block_context_to_markdown(block))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _build_block_context(
    block_ids: List[str],
    blocks_by_id: Dict[str, Dict[str, Any]],
    final_prd: str,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for block_id in _dedupe(block_ids):
        block = blocks_by_id.get(block_id)
        if not block:
            continue
        result.append({
            "block_id": block_id,
            "type": block.get("type", ""),
            "title": block.get("title", ""),
            "blocked_text": block.get("text", ""),
            "start_line": block.get("start_line"),
            "end_line": block.get("end_line"),
            "heading_path": block.get("heading_path") or [],
        })
    return result


def _block_context_to_markdown(block: Dict[str, Any]) -> str:
    lines = [f"### {block.get('block_id')} [{block.get('type')}] {block.get('title', '')}", ""]
    if block.get("heading_path"):
        lines.append(f"- heading_path: {' > '.join(block.get('heading_path') or [])}")
    if block.get("start_line") and block.get("end_line"):
        lines.append(f"- lines: {block.get('start_line')}-{block.get('end_line')}")
    lines.append("")
    lines.append("#### PRD 原文")
    lines.append(block.get("blocked_text", "").strip())
    return "\n".join(lines).strip()


def _compact_module(module: Dict[str, Any]) -> Dict[str, Any]:
    unit_type = module.get("unit_type") or "normal_lu"
    if unit_type == "integration_lu":
        block_ids = module.get("evidence_block_ids") or module.get("primary_block_ids") or module.get("block_ids") or []
    else:
        block_ids = module.get("primary_block_ids") or module.get("block_ids") or []
    return {
        "lu_id": module.get("lu_id", ""),
        "unit_type": unit_type,
        "title": module.get("title", ""),
        "summary": module.get("summary", ""),
        "covered_lu_ids": module.get("covered_lu_ids") or [],
        "integration_focus": module.get("flow_hint") or module.get("integration_focus", ""),
        "flow_hint": module.get("flow_hint") or module.get("integration_focus", ""),
        "flow_outline": module.get("flow_outline") or [],
        "excluded_atomic_focus": module.get("excluded_atomic_focus") or [],
        "evidence_block_ids": module.get("evidence_block_ids") or [],
        "block_ids": block_ids,
        "primary_block_ids": block_ids,
        "support_block_ids": module.get("support_block_ids") or [],
    }


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
