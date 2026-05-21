"""
PRD knowledge LU grouping normalization and validation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


def normalize_prd_knowledge(raw: Dict[str, Any], blocks_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    raw = raw or {}
    modules = _normalize_modules(raw.get("modules") or raw.get("lus") or [])
    integration_modules = _normalize_integration_modules(raw.get("integration_modules") or raw.get("integration_lus") or [])
    global_summary = str(raw.get("global_summary") or raw.get("global_kernel") or "").strip()
    block_roles = _normalize_block_roles(raw, modules)
    support_only_blocks = _support_only_blocks_from_roles(block_roles)
    knowledge = {
        "global_summary": global_summary,
        "global_kernel": global_summary,
        "global_block_ids": [block.get("block_id") for block in support_only_blocks if block.get("block_id")],
        "block_roles": block_roles,
        "support_only_blocks": support_only_blocks,
        "modules": modules,
        "integration_modules": integration_modules,
        "warnings": _as_string_list(raw.get("warnings") or raw.get("risks")),
    }
    return knowledge


def validate_prd_knowledge(knowledge: Dict[str, Any], blocks_by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    _check_duplicate_ids(issues, knowledge.get("modules") or [], "lu_id", "duplicate_lu_id")
    _check_duplicate_ids(issues, knowledge.get("integration_modules") or [], "lu_id", "duplicate_integration_lu_id")

    block_ids = set(blocks_by_id.keys())
    normal_lu_ids = _ids(knowledge.get("modules") or [], "lu_id")
    integration_lu_ids = _ids(knowledge.get("integration_modules") or [], "lu_id")
    overlap_lu_ids = sorted(normal_lu_ids & integration_lu_ids)
    if overlap_lu_ids:
        issues.append(_issue(
            "critical",
            "normal_integration_lu_id_overlap",
            f"普通 LU 和链路 LU 的 ID 不能重复: {', '.join(overlap_lu_ids)}",
            "integration_modules",
        ))
    valid_roles = {"primary", "support", "support_only"}
    role_entries = knowledge.get("block_roles") or []
    role_usage: Dict[str, List[str]] = {}
    role_by_id: Dict[str, str] = {}
    primary_usage: Dict[str, List[str]] = {}
    support_usage: Dict[str, List[str]] = {}

    if not knowledge.get("global_summary"):
        issues.append(_issue("warning", "missing_global_summary", "PRD Knowledge 缺少 global_summary", ""))

    if not role_entries:
        issues.append(_issue("critical", "missing_block_roles", "PRD Knowledge 缺少 block_roles 总账", ""))

    for entry in role_entries:
        if not isinstance(entry, dict):
            continue
        block_id = str(entry.get("block_id") or "")
        role = str(entry.get("role") or "").strip()
        if not block_id:
            issues.append(_issue("critical", "block_role_without_block_id", "block_roles 存在缺少 block_id 的条目", "block_roles"))
            continue
        if block_id not in block_ids:
            issues.append(_issue("critical", "missing_block_ref", f"block_roles 引用不存在: {block_id}", "block_roles"))
            continue
        if role not in valid_roles:
            issues.append(_issue("critical", "invalid_block_role", f"BLOCK role 非法: {block_id} -> {role}", block_id))
        role_usage.setdefault(block_id, []).append(role)

    for block_id, roles in role_usage.items():
        if len(roles) > 1:
            issues.append(_issue(
                "critical",
                "duplicate_block_role",
                f"block_roles 中同一 BLOCK 只能出现一次: {block_id} -> {', '.join(roles)}",
                block_id,
            ))
        if len(roles) == 1 and roles[0] in valid_roles:
            role_by_id[block_id] = roles[0]

    missing_role_blocks = sorted(block_ids - set(role_usage.keys()))
    if missing_role_blocks:
        issues.append(_issue(
            "critical",
            "block_roles_missing_blocks",
            f"block_roles 未覆盖全部 BLOCK: {', '.join(missing_role_blocks)}",
            "block_roles",
        ))

    for module in knowledge.get("modules") or []:
        lu_id = module.get("lu_id", "")
        unit_type = module.get("unit_type", "")
        if unit_type != "normal_lu":
            issues.append(_issue("warning", "normal_lu_unit_type_normalized", f"普通 LU unit_type 应为 normal_lu: {lu_id}", lu_id))
        primary_ids = module.get("primary_block_ids") or module.get("block_ids") or []
        support_ids = module.get("support_block_ids") or []
        if not primary_ids:
            issues.append(_issue("critical", "module_without_primary_blocks", f"LU 缺少 primary_block_ids: {lu_id}", lu_id))
        _check_refs(issues, primary_ids, block_ids, "missing_block_ref", lu_id)
        _check_refs(issues, support_ids, block_ids, "missing_block_ref", lu_id)
        overlap = sorted(set(primary_ids) & set(support_ids))
        if overlap:
            issues.append(_issue(
                "critical",
                "primary_support_overlap",
                f"LU 的 primary_block_ids 和 support_block_ids 重复: {', '.join(overlap)}",
                lu_id,
            ))
        for block_id in primary_ids:
            primary_usage.setdefault(block_id, []).append(str(lu_id))
            if block_id in block_ids:
                _check_expected_role(issues, role_by_id, block_id, "primary", lu_id, "primary_block_ids")
        for block_id in support_ids:
            support_usage.setdefault(block_id, []).append(str(lu_id))
            if block_id in block_ids:
                _check_expected_role(issues, role_by_id, block_id, "support", lu_id, "support_block_ids")

    for module in knowledge.get("integration_modules") or []:
        lu_id = module.get("lu_id", "")
        unit_type = module.get("unit_type", "")
        if unit_type != "integration_lu":
            issues.append(_issue("warning", "integration_lu_unit_type_normalized", f"链路 LU unit_type 应为 integration_lu: {lu_id}", lu_id))
        covered_lu_ids = module.get("covered_lu_ids") or []
        if len(covered_lu_ids) < 2:
            issues.append(_issue(
                "critical",
                "integration_lu_without_enough_covered_lus",
                f"链路 LU 必须覆盖至少 2 个普通 LU: {lu_id}",
                lu_id,
            ))
        flow_hint = str(module.get("flow_hint") or module.get("integration_focus") or "").strip()
        if not flow_hint:
            issues.append(_issue("critical", "integration_lu_missing_flow_hint", f"链路 LU 缺少 flow_hint: {lu_id}", lu_id))
        flow_outline = module.get("flow_outline") or []
        if not flow_outline:
            issues.append(_issue("critical", "integration_lu_missing_flow_outline", f"链路 LU 缺少 flow_outline: {lu_id}", lu_id))
        elif len(flow_outline) < 2:
            issues.append(_issue("warning", "integration_lu_short_flow_outline", f"链路 LU 的 flow_outline 过短: {lu_id}", lu_id))
        for covered_lu_id in covered_lu_ids:
            if covered_lu_id not in normal_lu_ids:
                issues.append(_issue(
                    "critical",
                    "integration_lu_missing_covered_lu_ref",
                    f"链路 LU 引用不存在的普通 LU: {covered_lu_id}",
                    lu_id,
                ))
        evidence_ids = module.get("evidence_block_ids") or module.get("primary_block_ids") or module.get("block_ids") or []
        support_ids = module.get("support_block_ids") or []
        if not evidence_ids:
            issues.append(_issue("critical", "integration_lu_without_evidence_blocks", f"链路 LU 缺少 evidence_block_ids: {lu_id}", lu_id))
        _check_refs(issues, evidence_ids, block_ids, "missing_block_ref", lu_id)
        _check_refs(issues, support_ids, block_ids, "missing_block_ref", lu_id)
        overlap = sorted(set(evidence_ids) & set(support_ids))
        if overlap:
            issues.append(_issue(
                "warning",
                "integration_evidence_support_overlap",
                f"链路 LU 的 evidence_block_ids 和 support_block_ids 重复: {', '.join(overlap)}",
                lu_id,
            ))
        for block_id in evidence_ids:
            if role_by_id.get(block_id) == "support_only":
                issues.append(_issue(
                    "critical",
                    "integration_evidence_support_only_block",
                    f"链路 LU 的 evidence_block_ids 不能引用 support_only BLOCK: {block_id}",
                    lu_id,
                ))
            elif role_by_id.get(block_id) == "support":
                support_usage.setdefault(block_id, []).append(str(lu_id))
        for block_id in support_ids:
            if role_by_id.get(block_id) == "support_only":
                issues.append(_issue(
                    "critical",
                    "integration_support_support_only_block",
                    f"链路 LU 的 support_block_ids 不能引用 support_only BLOCK: {block_id}",
                    lu_id,
                ))
            else:
                support_usage.setdefault(block_id, []).append(str(lu_id))

    for block_id, lu_ids in primary_usage.items():
        if block_id in block_ids and len(lu_ids) > 1:
            issues.append(_issue(
                "critical",
                "primary_block_used_by_multiple_lus",
                f"主需求 BLOCK 被多个 LU 引用，确认是否应合并 LU 或转为 support_block_ids: {block_id} -> {', '.join(lu_ids)}",
                block_id,
            ))

    primary_role_ids = {block_id for block_id, role in role_by_id.items() if role == "primary"}
    support_role_ids = {block_id for block_id, role in role_by_id.items() if role == "support"}

    unused_primary_roles = sorted(primary_role_ids - set(primary_usage.keys()))
    if unused_primary_roles:
        issues.append(_issue(
            "critical",
            "primary_role_not_used_by_lu",
            f"role=primary 的 BLOCK 必须出现在且只出现在一个 LU 的 primary_block_ids: {', '.join(unused_primary_roles)}",
            "block_roles",
        ))

    unused_support_roles = sorted(support_role_ids - set(support_usage.keys()))
    if unused_support_roles:
        issues.append(_issue(
            "critical",
            "support_role_not_used_by_lu",
            f"role=support 的 BLOCK 必须出现在至少一个 LU 的 support_block_ids: {', '.join(unused_support_roles)}",
            "block_roles",
        ))

    if not knowledge.get("modules"):
        issues.append(_issue("critical", "no_modules", "PRD Knowledge 未生成任何 LU 模块", ""))
    return issues


def knowledge_to_markdown(knowledge: Dict[str, Any]) -> str:
    lines = ["# PRD Knowledge", "", "## Global Summary", knowledge.get("global_summary", ""), ""]
    lines.append("## Block Roles")
    block_roles = knowledge.get("block_roles") or []
    if block_roles:
        for block in block_roles:
            reason = block.get("reason", "")
            suffix = f" - {reason}" if reason else ""
            lines.append(f"- {block.get('block_id')}: {block.get('role', '')}{suffix}")
    else:
        lines.append("None")
    lines.append("")
    lines.append("## Modules")
    for module in knowledge.get("modules") or []:
        lines.append(f"### {module.get('lu_id')} {module.get('title', '')}")
        lines.append(f"- unit_type: {module.get('unit_type', 'normal_lu')}")
        lines.append(f"- summary: {module.get('summary', '')}")
        lines.append(f"- primary: {', '.join(module.get('primary_block_ids') or module.get('block_ids') or [])}")
        lines.append(f"- support: {', '.join(module.get('support_block_ids') or []) or 'None'}")
        lines.append("")
    lines.append("## Integration Modules")
    integration_modules = knowledge.get("integration_modules") or []
    if integration_modules:
        for module in integration_modules:
            lines.append(f"### {module.get('lu_id')} {module.get('title', '')}")
            lines.append(f"- unit_type: {module.get('unit_type', 'integration_lu')}")
            lines.append(f"- summary: {module.get('summary', '')}")
            lines.append(f"- covered_lus: {', '.join(module.get('covered_lu_ids') or [])}")
            lines.append(f"- flow_hint: {module.get('flow_hint') or module.get('integration_focus', '')}")
            outline = module.get('flow_outline') or []
            if outline:
                lines.append(f"- flow_outline: {' | '.join(outline)}")
            lines.append(f"- evidence: {', '.join(module.get('evidence_block_ids') or module.get('primary_block_ids') or module.get('block_ids') or [])}")
            lines.append(f"- support: {', '.join(module.get('support_block_ids') or []) or 'None'}")
            excluded = module.get('excluded_atomic_focus') or []
            if excluded:
                lines.append(f"- excluded_atomic_focus: {' | '.join(excluded)}")
            lines.append("")
    else:
        lines.append("None")
        lines.append("")
    if knowledge.get("warnings"):
        lines.append("## Warnings")
        for warning in knowledge.get("warnings") or []:
            lines.append(f"- {warning}")
    return "\n".join(lines).strip() + "\n"


def _normalize_modules(values: Any) -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    for index, item in enumerate(values if isinstance(values, list) else [], 1):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("lu_id") or item.get("id") or f"LU-{index:03d}").strip()
        lu_id = _normalize_id(raw_id, "LU", index)
        modules.append({
            "lu_id": lu_id,
            "unit_type": "normal_lu",
            "title": str(item.get("title") or item.get("name") or lu_id).strip(),
            "summary": str(item.get("summary") or item.get("brief") or "").strip(),
            "primary_block_ids": _normalize_block_ids(
                item.get("primary_block_ids")
                or item.get("block_ids")
                or item.get("evidence_block_ids")
                or item.get("requirement_ids")
            ),
            "support_block_ids": _normalize_block_ids(item.get("support_block_ids") or item.get("supporting_block_ids")),
        })
        modules[-1]["block_ids"] = modules[-1]["primary_block_ids"]
    return modules


def _normalize_integration_modules(values: Any) -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    for index, item in enumerate(values if isinstance(values, list) else [], 1):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("lu_id") or item.get("id") or f"INT-{index:03d}").strip()
        lu_id = _normalize_id(raw_id, "INT", index)
        module = {
            "lu_id": lu_id,
            "unit_type": "integration_lu",
            "title": str(item.get("title") or item.get("name") or lu_id).strip(),
            "summary": str(item.get("summary") or item.get("brief") or item.get("flow_hint") or item.get("integration_focus") or "").strip(),
            "covered_lu_ids": _normalize_lu_ids(item.get("covered_lu_ids") or item.get("covered_modules") or item.get("related_lu_ids")),
            "evidence_block_ids": _normalize_block_ids(
                item.get("evidence_block_ids")
                or item.get("primary_block_ids")
                or item.get("block_ids")
                or item.get("requirement_ids")
            ),
            "support_block_ids": _normalize_block_ids(item.get("support_block_ids") or item.get("supporting_block_ids")),
            "flow_hint": str(item.get("flow_hint") or item.get("integration_focus") or item.get("focus") or item.get("scope") or "").strip(),
            "flow_outline": _normalize_text_list(item.get("flow_outline") or item.get("flow_steps") or item.get("integration_outline")),
            "excluded_atomic_focus": _normalize_text_list(item.get("excluded_atomic_focus") or item.get("excluded_focus") or item.get("atomic_exclusions")),
        }
        module["integration_focus"] = module["flow_hint"]
        module["primary_block_ids"] = _normalize_block_ids(item.get("primary_block_ids") or item.get("block_ids"))
        module["block_ids"] = module["evidence_block_ids"]
        modules.append(module)
    return modules


def _normalize_block_roles(raw: Dict[str, Any], modules: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    raw_roles = raw.get("block_roles")
    if isinstance(raw_roles, list) and raw_roles:
        roles: List[Dict[str, str]] = []
        for item in raw_roles:
            if not isinstance(item, dict):
                continue
            block_ids = _normalize_block_ids(item.get("block_id") or item.get("id") or item.get("block_ids"))
            role = _normalize_role(item.get("role") or item.get("block_role"))
            reason = _compact_reason(item.get("reason") or item.get("summary") or item.get("note"))
            for block_id in block_ids:
                roles.append({"block_id": block_id, "role": role, "reason": reason})
        return roles

    roles = []
    for block_id in _normalize_block_ids(
        raw.get("support_only_blocks")
        or raw.get("support_only_block_ids")
        or raw.get("global_block_ids")
        or raw.get("global_blocks")
    ):
        roles.append({"block_id": block_id, "role": "support_only", "reason": ""})
    for module in modules:
        for block_id in module.get("primary_block_ids") or module.get("block_ids") or []:
            roles.append({"block_id": block_id, "role": "primary", "reason": ""})
        for block_id in module.get("support_block_ids") or []:
            roles.append({"block_id": block_id, "role": "support", "reason": ""})
    return roles


def _normalize_role(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "main": "primary",
        "core": "primary",
        "requirement": "primary",
        "functional": "primary",
        "testable": "primary",
        "supporting": "support",
        "aux": "support",
        "auxiliary": "support",
        "helper": "support",
        "context": "support",
        "global": "support_only",
        "global_context": "support_only",
        "background": "support_only",
        "archive": "support_only",
        "read_only": "support_only",
        "readonly": "support_only",
        "reference": "support_only",
        "index": "support_only",
        "excluded": "support_only",
    }
    return mapping.get(text, text)


def _support_only_blocks_from_roles(block_roles: List[Dict[str, str]]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for item in block_roles or []:
        if item.get("role") != "support_only":
            continue
        block_id = item.get("block_id", "")
        if not block_id or block_id in seen:
            continue
        seen.add(block_id)
        result.append({"block_id": block_id, "reason": item.get("reason", "")})
    return result


def _normalize_support_only_blocks(values: Any) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict):
                block_ids = _normalize_block_ids(item.get("block_id") or item.get("id") or item.get("block_ids"))
                reason = _compact_reason(item.get("reason") or item.get("summary") or item.get("note"))
                for block_id in block_ids:
                    blocks.append({"block_id": block_id, "reason": reason})
            else:
                for block_id in _normalize_block_ids(item):
                    blocks.append({"block_id": block_id, "reason": ""})
    else:
        for block_id in _normalize_block_ids(values):
            blocks.append({"block_id": block_id, "reason": ""})
    result: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for block in blocks:
        block_id = block.get("block_id", "")
        if not block_id or block_id in seen:
            continue
        seen.add(block_id)
        result.append(block)
    return result


def _normalize_text_list(values: Any) -> List[str]:
    items: List[str] = []
    raw_items = values if isinstance(values, list) else _as_string_list(values)
    for item in raw_items:
        text = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", str(item or "")).strip()
        if text:
            items.append(text)
    return _dedupe(items)


def _compact_reason(value: Any, max_chars: int = 30) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _normalize_block_ids(values: Any) -> List[str]:
    result = []
    for value in _as_string_list(values):
        text = str(value).upper().strip()
        match = re.search(r"B[-_]?(\d{1,4})", text)
        if match:
            result.append(f"B-{int(match.group(1)):03d}")
    return _dedupe(result)


def _normalize_lu_ids(values: Any) -> List[str]:
    result = []
    for value in _as_string_list(values):
        text = str(value).upper().strip()
        match = re.search(r"LU[-_]?(\d{1,4})", text)
        if match:
            result.append(f"LU-{int(match.group(1)):03d}")
    return _dedupe(result)


def _normalize_id(value: Any, prefix: str, index: int) -> str:
    text = str(value or "").strip().upper().replace("_", "-")
    prefix = prefix.upper()
    match = re.search(rf"{re.escape(prefix)}[-\s]?(\d{{1,4}})", text)
    if match:
        return f"{prefix}-{int(match.group(1)):03d}"
    return f"{prefix}-{index:03d}" if index else text


def _ids(items: List[Dict[str, Any]], key: str) -> Set[str]:
    return {str(item.get(key)) for item in items if item.get(key)}


def _check_duplicate_ids(issues: List[Dict[str, Any]], items: List[Dict[str, Any]], key: str, code: str) -> None:
    seen: Set[str] = set()
    for item in items:
        value = str(item.get(key) or "")
        if not value:
            continue
        if value in seen:
            issues.append(_issue("critical", code, f"ID 重复: {value}", value))
        seen.add(value)


def _check_refs(
    issues: List[Dict[str, Any]],
    values: List[str],
    allowed: Set[str],
    code: str,
    owner_id: str,
) -> None:
    for value in values or []:
        if value not in allowed:
            issues.append(_issue("critical", code, f"引用不存在: {value}", owner_id))


def _check_expected_role(
    issues: List[Dict[str, Any]],
    role_by_id: Dict[str, str],
    block_id: str,
    expected_role: str,
    lu_id: str,
    field_name: str,
) -> None:
    actual_role = role_by_id.get(block_id)
    if actual_role == expected_role:
        return
    if actual_role:
        issues.append(_issue(
            "critical",
            "block_role_module_mismatch",
            f"{field_name} 引用的 BLOCK role 应为 {expected_role}: {block_id} 当前为 {actual_role}",
            lu_id,
        ))
    else:
        issues.append(_issue(
            "critical",
            "module_block_missing_role",
            f"{field_name} 引用的 BLOCK 未在 block_roles 中声明有效 role: {block_id}",
            lu_id,
        ))


def _as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _issue(severity: str, code: str, message: str, owner_id: str) -> Dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "owner_id": owner_id,
    }
