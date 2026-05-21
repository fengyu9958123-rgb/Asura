"""
PRD block boundary planning and parsing helpers.

The final PRD remains the product fact source. Block Builder only returns line
ranges; code inserts BLOCK markers into the original PRD so block_id can always
be mapped back to unchanged source text.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple


BLOCK_TYPES = {
    "SECTION",
    "TABLE",
    "FLOW",
    "APPENDIX",
}

TYPE_ALIASES = {
    "OVERVIEW": "SECTION",
    "ENTRY": "SECTION",
    "INPUT": "SECTION",
    "ACTION": "SECTION",
    "DISPLAY": "SECTION",
    "DATA": "TABLE",
    "RULE": "SECTION",
    "STATE": "SECTION",
    "EXCEPTION": "SECTION",
    "PERMISSION": "SECTION",
}

BLOCK_RE = re.compile(
    r"<!--\s*BLOCK:(?P<id>B-\d{3,4})\s+TYPE:(?P<type>[A-Z_]+)(?:\s+LINES:(?P<start>\d+)-(?P<end>\d+))?\s*-->",
    re.IGNORECASE,
)
BLOCK_MARKER_LINE_RE = re.compile(
    r"^\s*<!--\s*BLOCK:B-\d{3,4}\s+TYPE:[A-Z_]+(?:\s+LINES:\d+-\d+)?\s*-->\s*$",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")


def build_numbered_prd(final_prd: str) -> str:
    """Return final PRD with stable 1-based line numbers for boundary planning."""
    lines = _logical_lines(final_prd)
    if not lines:
        return ""
    width = max(4, len(str(len(lines))))
    return "\n".join(f"{index:0{width}d}: {line}" for index, line in enumerate(lines, 1))


def normalize_block_plan(raw: Any, final_prd: str) -> Dict[str, Any]:
    """Normalize agent block boundary output and assign stable block IDs by line order."""
    raw_blocks = raw.get("blocks") if isinstance(raw, dict) else raw
    blocks: List[Dict[str, Any]] = []
    for item in raw_blocks if isinstance(raw_blocks, list) else []:
        if not isinstance(item, dict):
            continue
        start_line = _to_int(item.get("start_line") or item.get("start") or item.get("line_start"))
        end_line = _to_int(item.get("end_line") or item.get("end") or item.get("line_end"))
        if start_line is None or end_line is None:
            parsed_start, parsed_end = _parse_line_range(item.get("lines") or item.get("line_range"))
            if start_line is None:
                start_line = parsed_start
            if end_line is None:
                end_line = parsed_end
        start_line = _snap_start_to_previous_heading(_logical_lines(final_prd), start_line)
        block_type = _normalize_block_type(item.get("type"))
        blocks.append({
            "block_id": "",
            "type": block_type,
            "title": str(item.get("title") or item.get("name") or "").strip(),
            "start_line": start_line,
            "end_line": end_line,
        })

    blocks.sort(key=lambda block: (
        block["start_line"] if block["start_line"] is not None else 10**9,
        block["end_line"] if block["end_line"] is not None else 10**9,
    ))
    prd_lines = _logical_lines(final_prd)
    line_count = len(prd_lines)
    for index, block in enumerate(blocks, 1):
        block["block_id"] = f"B-{index:03d}"
        start_line = block.get("start_line")
        next_start = blocks[index]["start_line"] if index < len(blocks) else None
        if isinstance(start_line, int):
            computed_end = (next_start - 1) if isinstance(next_start, int) else line_count
            if computed_end < start_line:
                computed_end = start_line
            block["end_line"] = computed_end
            block["heading_path"] = _heading_path_for_range(prd_lines, start_line, computed_end)
            if not block.get("title"):
                block["title"] = _title_for_range(prd_lines, start_line, computed_end) or block["block_id"]
        elif not block.get("title"):
            block["title"] = block["block_id"]

    warnings = raw.get("warnings") if isinstance(raw, dict) else []
    return {
        "blocks": blocks,
        "warnings": _as_string_list(warnings),
    }


def validate_block_plan(plan: Dict[str, Any], final_prd: str) -> List[Dict[str, Any]]:
    """Validate that block starts are ordered and the derived ranges can cover the PRD."""
    issues: List[Dict[str, Any]] = []
    blocks = plan.get("blocks") if isinstance(plan, dict) else []
    blocks = blocks if isinstance(blocks, list) else []
    line_count = len(_logical_lines(final_prd))
    if line_count and not blocks:
        issues.append(_issue("critical", "no_block_plan", "Block Builder 未生成任何 BLOCK 行范围", ""))
        return issues
    if not line_count:
        if blocks:
            issues.append(_issue("critical", "empty_prd_with_blocks", "PRD 为空但存在 BLOCK 行范围", ""))
        return issues

    expected_start = 1
    seen_ids: Set[str] = set()
    for index, block in enumerate(blocks, 1):
        block_id = str(block.get("block_id") or f"B-{index:03d}")
        start_line = block.get("start_line")
        end_line = block.get("end_line")
        if block_id in seen_ids:
            issues.append(_issue("critical", "duplicate_block_id", f"BLOCK 编号重复: {block_id}", block_id))
        seen_ids.add(block_id)
        if block_id != f"B-{index:03d}":
            issues.append(_issue("critical", "non_sequential_block_id", f"BLOCK 编号不连续: {block_id}", block_id))
        if block.get("type") not in BLOCK_TYPES:
            issues.append(_issue("critical", "unknown_block_type", f"未知 BLOCK 类型: {block.get('type')}", block_id))
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            issues.append(_issue("critical", "invalid_line_range", f"BLOCK 行范围不是整数: {block_id}", block_id))
            continue
        if start_line < 1 or end_line < 1 or start_line > line_count or end_line > line_count:
            issues.append(_issue(
                "critical",
                "line_range_out_of_bounds",
                f"BLOCK 行范围超出 PRD 行数: {block_id} {start_line}-{end_line}, total={line_count}",
                block_id,
            ))
            continue
        if start_line > end_line:
            issues.append(_issue("critical", "reversed_line_range", f"BLOCK 起始行晚于结束行: {block_id}", block_id))
            continue
        if index == 1 and start_line != 1:
            issues.append(_issue("critical", "first_block_not_starting_at_line_one", "首个 BLOCK 必须从第 1 行开始", block_id))
        if start_line < expected_start:
            issues.append(_issue(
                "critical",
                "overlapping_block_ranges",
                f"BLOCK 起始行与前一个 BLOCK 重叠: {block_id} start={start_line}, expected>={expected_start}",
                block_id,
            ))
        expected_start = start_line + 1

    if blocks and blocks[-1].get("end_line") != line_count:
        issues.append(_issue(
            "critical",
            "missing_tail_lines",
            f"BLOCK 行范围未覆盖到 PRD 末尾: last_end={blocks[-1].get('end_line')}, total={line_count}",
            "",
        ))
    if len(blocks) == 1 and _heading_count(final_prd) > 2:
        issues.append(_issue("warning", "single_block_for_multi_section_prd", "多章节 PRD 仅生成 1 个 BLOCK", "B-001"))
    return issues


def render_blocked_prd(final_prd: str, plan: Dict[str, Any]) -> str:
    """Insert BLOCK markers before original PRD lines without changing source text."""
    chunks = str(final_prd or "").splitlines(keepends=True)
    markers_by_line = {
        int(block["start_line"]): (
            f"<!-- BLOCK:{block['block_id']} TYPE:{block['type']} "
            f"LINES:{block['start_line']}-{block['end_line']} -->\n"
        )
        for block in plan.get("blocks") or []
        if isinstance(block.get("start_line"), int)
    }
    rendered: List[str] = []
    for index, chunk in enumerate(chunks, 1):
        marker = markers_by_line.get(index)
        if marker:
            rendered.append(marker)
        rendered.append(chunk)
    return "".join(rendered)


def strip_block_markers(blocked_prd_md: str) -> str:
    """Remove generated BLOCK marker lines and recover the original PRD text."""
    lines = str(blocked_prd_md or "").splitlines(keepends=True)
    return "".join(line for line in lines if not BLOCK_MARKER_LINE_RE.match(line.rstrip("\r\n")))


def parse_prd_blocks(blocked_prd_md: str) -> List[Dict[str, Any]]:
    """Parse block anchors and return ordered block records."""
    matches = list(BLOCK_RE.finditer(blocked_prd_md or ""))
    blocks: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        block_id = match.group("id").upper()
        block_type = _normalize_block_type(match.group("type"))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(blocked_prd_md or "")
        text = _drop_marker_line_break((blocked_prd_md or "")[start:end])
        title = _extract_title(text) or block_id
        start_line = _to_int(match.group("start"))
        end_line = _to_int(match.group("end"))
        blocks.append({
            "block_id": block_id,
            "type": block_type,
            "title": title,
            "heading_path": _extract_heading_path(text),
            "start_line": start_line,
            "end_line": end_line,
            "text": text,
            "order": index + 1,
        })
    return blocks


def blocks_by_id(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(block.get("block_id")): block
        for block in blocks or []
        if block.get("block_id")
    }


def validate_prd_blocks(
    blocks: List[Dict[str, Any]],
    final_prd: str,
    blocked_prd_md: str = "",
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    seen = set()
    for block in blocks or []:
        block_id = str(block.get("block_id") or "")
        block_type = str(block.get("type") or "")
        if not block_id:
            issues.append(_issue("critical", "missing_block_id", "BLOCK 缺少 block_id", block_id))
            continue
        if block_id in seen:
            issues.append(_issue("critical", "duplicate_block_id", f"BLOCK 编号重复: {block_id}", block_id))
        seen.add(block_id)
        if block_type not in BLOCK_TYPES:
            issues.append(_issue("warning", "unknown_block_type", f"未知 BLOCK 类型: {block_type}", block_id))
        if not str(block.get("text") or "").strip():
            issues.append(_issue("critical", "empty_block", f"BLOCK 内容为空: {block_id}", block_id))
        if not isinstance(block.get("start_line"), int) or not isinstance(block.get("end_line"), int):
            issues.append(_issue("critical", "missing_line_range", f"BLOCK 缺少行范围: {block_id}", block_id))
    if not blocks:
        issues.append(_issue("critical", "no_blocks", "Blocked PRD 未解析到任何 BLOCK", ""))
    if blocked_prd_md and strip_block_markers(blocked_prd_md) != str(final_prd or ""):
        issues.append(_issue("critical", "blocked_prd_not_reversible", "去除 BLOCK 标记后无法还原最终 PRD 原文", ""))
    return issues


def build_block_catalog(blocks: List[Dict[str, Any]], *, max_outline_chars: int = 260) -> List[Dict[str, Any]]:
    return [
        {
            "block_id": block.get("block_id"),
            "type": block.get("type"),
            "title": block.get("title"),
            "start_line": block.get("start_line"),
            "end_line": block.get("end_line"),
            "heading_path": block.get("heading_path") or [],
            "content_outline": _compact_text(block.get("text", ""), max_outline_chars),
        }
        for block in blocks or []
    ]


def block_to_markdown(block: Dict[str, Any]) -> str:
    return (
        f"### {block.get('block_id')} [{block.get('type')}] {block.get('title', '')}\n\n"
        f"{block.get('text', '').strip()}\n"
    ).strip()


def _extract_title(text: str) -> str:
    match = HEADING_RE.search(text or "")
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(2)).strip()


def _extract_heading_path(text: str) -> List[str]:
    headings: List[str] = []
    for match in HEADING_RE.finditer(text or ""):
        level = len(match.group(1))
        title = re.sub(r"\s+", " ", match.group(2)).strip()
        headings = headings[:level - 1]
        headings.append(title)
    return headings


def _heading_path_for_range(lines: List[str], start_line: int, end_line: int) -> List[str]:
    headings: List[str] = []
    path_at_start: List[str] = []
    path_in_block: List[str] = []
    for index, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            title = re.sub(r"\s+", " ", match.group(2)).strip()
            headings = headings[:level - 1]
            headings.append(title)
        if index == start_line:
            path_at_start = list(headings)
        if start_line <= index <= end_line and match:
            path_in_block = list(headings)
        if index >= end_line:
            break
    return path_in_block or path_at_start


def _title_for_range(lines: List[str], start_line: int, end_line: int) -> str:
    for index in range(max(1, start_line), min(len(lines), end_line) + 1):
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", lines[index - 1])
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    for index in range(max(1, start_line), min(len(lines), end_line) + 1):
        text = lines[index - 1].strip()
        if text:
            return _compact_text(text, 40)
    return ""


def _snap_start_to_previous_heading(lines: List[str], start_line: Optional[int]) -> Optional[int]:
    if not isinstance(start_line, int) or start_line <= 1 or start_line > len(lines):
        return start_line
    current = lines[start_line - 1].strip()
    previous = lines[start_line - 2].strip()
    if not current and re.match(r"^#{1,6}\s+", previous):
        return start_line - 1
    return start_line


def _drop_marker_line_break(text: str) -> str:
    if text.startswith("\r\n"):
        return text[2:]
    if text.startswith("\n"):
        return text[1:]
    return text


def _logical_lines(text: str) -> List[str]:
    return str(text or "").splitlines()


def _heading_count(text: str) -> int:
    return len(HEADING_RE.findall(text or ""))


def _normalize_block_type(value: Any) -> str:
    text = str(value or "SECTION").strip().upper()
    text = TYPE_ALIASES.get(text, text)
    return text if text in BLOCK_TYPES else "SECTION"


def _parse_line_range(value: Any) -> Tuple[Optional[int], Optional[int]]:
    match = re.search(r"(\d+)\s*[-~至,，]\s*(\d+)", str(value or ""))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _compact_text(content: Any, max_chars: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _issue(severity: str, code: str, message: str, block_id: str) -> Dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "block_id": block_id,
    }
