"""
Utilities for extracting the actual PRD body from model responses.

Final PRDs are later used as factual input for testcase agents. Keep this
cleanup narrow: remove model wrappers and integration reports, not business
content inside the PRD.
"""

import re
from typing import Iterable, Optional, Set

from services.generation.llm_response_cleaner import strip_model_reasoning


def clean_prd_document(content: str) -> str:
    """Return a PRD-only document from a model response or stored PRD field."""
    text = str(content or "").strip()
    if not text:
        return ""

    text = _extract_marked_prd(text)
    text = strip_model_reasoning(text)
    text = _strip_outer_markdown_fence(text)
    text = _trim_before_prd_heading(text)
    text = _remove_human_confirm_blocks(text)
    text = _trim_after_non_prd_report(text)
    text = _repair_markdown_table_separator_rows(text)
    return text.strip()


def align_playback_speeds_to_sources(content: str, *sources: str) -> str:
    """Remove negative playback-speed values that are absent from the source material."""
    text = str(content or "")
    if not text:
        return ""
    source_text = "\n".join(str(source or "") for source in sources)
    if not re.search(r"(播放倍速|倍速选项|可选倍速|负倍速|快退)", source_text):
        return text
    allowed = _extract_negative_playback_speeds(source_text)
    return _remove_unsupported_negative_playback_speeds(text, allowed)


def _extract_marked_prd(text: str) -> str:
    start_marker = "<PRD_DOCUMENT_START>"
    end_markers = ("</PRD_DOCUMENT_END>", "<PRD_DOCUMENT_END>")

    start_idx = text.find(start_marker)
    if start_idx == -1:
        return text

    content_start = start_idx + len(start_marker)
    end_idx = -1
    for marker in end_markers:
        idx = text.find(marker, content_start)
        if idx != -1:
            end_idx = idx
            break

    if end_idx == -1 or end_idx <= content_start:
        return text
    return text[content_start:end_idx].strip()


def _strip_outer_markdown_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)```", text.strip(), flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def _trim_before_prd_heading(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("# "):
            continue
        if any(keyword in stripped for keyword in ("PRD", "需求", "产品文档", "产品说明")):
            return "\n".join(lines[index:]).strip()
    return text


def _trim_after_non_prd_report(text: str) -> str:
    lines = text.splitlines()
    cut_index = None
    for index, line in enumerate(lines):
        heading = line.strip().lstrip("#").strip()
        normalized = re.sub(r"\s+", "", heading)
        if _is_non_prd_report_heading(normalized):
            cut_index = _trim_preceding_separator(lines, index)
            break

    if cut_index is None:
        return text
    return "\n".join(lines[:cut_index]).rstrip()


def _remove_human_confirm_blocks(text: str) -> str:
    """Remove unresolved human-confirmation blocks from PRD body text."""
    if "<HUMAN_CONFIRM_START>" not in text:
        return text

    cleaned = re.sub(
        r"```[^\n]*\n?\s*<HUMAN_CONFIRM_START>.*?<HUMAN_CONFIRM_END>\s*```",
        "",
        text,
        flags=re.DOTALL,
    )
    cleaned = re.sub(
        r"<HUMAN_CONFIRM_START>.*?<HUMAN_CONFIRM_END>",
        "",
        cleaned,
        flags=re.DOTALL,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _repair_markdown_table_separator_rows(text: str) -> str:
    lines = text.splitlines()
    repaired: list[str] = []
    for index, line in enumerate(lines):
        if not _is_table_row(line):
            repaired.append(line)
            continue
        previous_line = lines[index - 1] if index > 0 else ""
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if _is_table_row(previous_line) and _is_table_row(next_line) and _looks_like_broken_separator(line):
            cell_count = max(1, len(line.strip().strip("|").split("|")))
            repaired.append("| " + " | ".join(["---"] * cell_count) + " |")
            continue
        repaired.append(line)
    return "\n".join(repaired)


def _is_table_row(line: str) -> bool:
    stripped = str(line or "").strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _looks_like_broken_separator(line: str) -> bool:
    cells = [cell.strip() for cell in str(line or "").strip().strip("|").split("|")]
    if not cells:
        return False
    separator_cells = [cell for cell in cells if re.fullmatch(r":?-{3,}:?", cell)]
    return len(separator_cells) >= max(1, len(cells) - 1)


def _extract_negative_playback_speeds(text: str) -> Set[str]:
    speeds: Set[str] = set()
    if not re.search(r"(播放倍速|倍速选项|可选倍速|负倍速|快退)", text):
        return speeds
    for match in re.finditer(r"-(\d+(?:\.\d+)?)x", text, flags=re.IGNORECASE):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        speeds.add(f"-{value:g}x")
    return speeds


def _normalize_negative_speed_token(token: str) -> Optional[str]:
    try:
        value = float(token.strip().lower().lstrip("-").rstrip("x"))
    except ValueError:
        return None
    return f"-{value:g}x"


def _remove_unsupported_negative_playback_speeds(text: str, allowed_negative_speeds: Set[str]) -> str:
    """Drop hallucinated negative playback-speed options while preserving confirmed ones."""
    if not re.search(r"(播放倍速|倍速选项|可选倍速|负倍速)", text):
        return text

    lines = text.splitlines()
    cleaned_lines = []
    in_playback_speed_section = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^#{1,6}\s+", stripped):
            in_playback_speed_section = bool(re.search(r"(播放倍速|倍速选项|可选倍速)", stripped))

        is_speed_context = in_playback_speed_section or bool(re.search(r"(播放倍速|倍速选项|可选倍速)", line))
        if is_speed_context and re.search(r"-\d+(?:\.\d+)?x", line, flags=re.IGNORECASE):
            cleaned_line = _remove_unsupported_negative_speed_tokens(line, allowed_negative_speeds)
            if _is_empty_speed_table_row(line, cleaned_line, allowed_negative_speeds):
                continue
            line = cleaned_line

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _remove_unsupported_negative_speed_tokens(line: str, allowed_negative_speeds: Set[str]) -> str:
    def replacement(match: re.Match) -> str:
        token = match.group(0)
        normalized = _normalize_negative_speed_token(token)
        if normalized and normalized in allowed_negative_speeds:
            return token
        return ""

    cleaned = re.sub(r"-\d+(?:\.\d+)?x", replacement, line, flags=re.IGNORECASE)
    cleaned = re.sub(r"([、,，])\s*([、,，]\s*)+", r"\1", cleaned)
    cleaned = re.sub(r"\|\s*[、,，]\s*", "| ", cleaned)
    cleaned = re.sub(r"\s*[、,，]\s*\|", " |", cleaned)
    cleaned = re.sub(r"([：:])\s*[、,，]\s*", r"\1 ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _is_empty_speed_table_row(original_line: str, cleaned_line: str, allowed_negative_speeds: Set[str]) -> bool:
    stripped_original = original_line.strip()
    if not (stripped_original.startswith("|") and stripped_original.endswith("|")):
        return False
    if not re.search(r"-\d+(?:\.\d+)?x", original_line, flags=re.IGNORECASE):
        return False
    original_cells = [cell.strip() for cell in stripped_original.strip("|").split("|")]
    cleaned_cells = [cell.strip() for cell in cleaned_line.strip().strip("|").split("|")]
    if original_cells and re.fullmatch(r"-\d+(?:\.\d+)?x", original_cells[0], flags=re.IGNORECASE):
        normalized = _normalize_negative_speed_token(original_cells[0])
        if normalized not in allowed_negative_speeds and cleaned_cells and not cleaned_cells[0]:
            return True
    cells = [cell.strip() for cell in cleaned_line.strip().strip("|").split("|")]
    return all(not cell for cell in cells)


def _is_non_prd_report_heading(normalized_heading: str) -> bool:
    exact_headings = {
        "整合清单",
        "已整合的人工确认问题",
        "整合统计",
        "整合方式分布",
        "关键信息保留",
    }
    if normalized_heading in exact_headings:
        return True
    return normalized_heading.startswith("已整合的人工确认问题")


def _trim_preceding_separator(lines: Iterable[str], index: int) -> int:
    result = index
    while result > 0 and not str(lines[result - 1]).strip():
        result -= 1
    if result > 0 and re.fullmatch(r"-{3,}", str(lines[result - 1]).strip()):
        result -= 1
    return result
