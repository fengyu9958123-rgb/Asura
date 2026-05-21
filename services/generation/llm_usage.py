"""LLM usage and cost accounting for LangGraph pipeline calls."""

from __future__ import annotations

import json
import math
import re
import threading
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.config.pricing import calculate_cost, pricing_snapshot_from_config


_CURRENT_RECORDER: ContextVar["UsageRecorder | None"] = ContextVar("llm_usage_recorder", default=None)
_CURRENT_STAGE: ContextVar[str] = ContextVar("llm_usage_stage", default="")


def approximate_tokens(text: Any) -> int:
    value = _stringify_content(text)
    if not value:
        return 0
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", value))
    latin_words = len(re.findall(r"[A-Za-z0-9_]+", value))
    punctuation = len(re.findall(r"[^\sA-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", value))
    spaces = len(re.findall(r"\s+", value))
    return int(math.ceil(cjk + latin_words * 1.25 + punctuation * 0.35 + spaces * 0.05))


def _stringify_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "text":
                    parts.append(str(item.get("text") or ""))
                elif item_type == "image_url":
                    parts.append("[image]")
                else:
                    parts.append(_stringify_content(item))
            else:
                parts.append(_stringify_content(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def usage_context(recorder: "UsageRecorder | None", stage: str = ""):
    class _UsageContext:
        def __enter__(self):
            self._recorder_token = _CURRENT_RECORDER.set(recorder)
            self._stage_token = _CURRENT_STAGE.set(stage or "")
            return recorder

        def __exit__(self, exc_type, exc, tb):
            _CURRENT_STAGE.reset(self._stage_token)
            _CURRENT_RECORDER.reset(self._recorder_token)
            return False

    return _UsageContext()


def get_current_recorder() -> "UsageRecorder | None":
    return _CURRENT_RECORDER.get()


def get_current_stage() -> str:
    return _CURRENT_STAGE.get()


class UsageRecorder:
    """Append-only task usage ledger with a computed summary."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.usage_dir = self.output_dir / "usage"
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.usage_dir / "llm_usage.json"
        self.summary_path = self.usage_dir / "llm_usage_summary.json"
        self._lock = threading.Lock()

    def record_agent_call(
        self,
        *,
        agent: Any,
        prompt: Any,
        response: Any,
        stage: str = "",
        usage: Optional[Dict[str, Any]] = None,
        estimated: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        config = _agent_primary_config(agent)
        system_message = str(getattr(agent, "system_message", "") or "")
        if usage:
            input_tokens = _first_int(usage, "input_tokens", "prompt_tokens")
            output_tokens = _first_int(usage, "output_tokens", "completion_tokens")
            total_tokens = _first_int(usage, "total_tokens")
            if total_tokens <= 0:
                total_tokens = input_tokens + output_tokens
            cached_input_tokens = _cached_input_tokens(usage)
        else:
            input_tokens = approximate_tokens(system_message) + approximate_tokens(prompt)
            output_tokens = approximate_tokens(response)
            total_tokens = input_tokens + output_tokens
            cached_input_tokens = 0

        pricing = pricing_snapshot_from_config(config)
        cost = calculate_cost(input_tokens, output_tokens, pricing, cached_input_tokens)
        record = {
            "id": "",
            "timestamp": datetime.now().isoformat(),
            "stage": stage or get_current_stage() or "",
            "agent": str(getattr(agent, "name", "") or "agent"),
            "model_type": str(config.get("model_type") or ""),
            "model": str(config.get("model") or _usage_model(usage) or ""),
            "api": str(config.get("api") or ""),
            "base_url": _safe_base_url(config.get("base_url")),
            "usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated": bool(estimated),
                "source": "estimated" if estimated else "provider",
                "raw": usage if isinstance(usage, dict) else {},
            },
            "pricing_snapshot": pricing,
            "cost": cost,
            "currency": pricing.get("currency") if cost is not None else "",
            "metadata": metadata or {},
        }
        return self.append_record(record)

    def append_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            records = self.read_records()
            record = dict(record)
            record["id"] = record.get("id") or f"LLM-{len(records) + 1:04d}"
            records.append(record)
            self.records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            self.summary_path.write_text(json.dumps(self.summarize(records), ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def read_records(self) -> List[Dict[str, Any]]:
        if not self.records_path.exists():
            return []
        try:
            payload = json.loads(self.records_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except Exception:
            return []

    @staticmethod
    def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "calls": len(records),
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_calls": 0,
            "provider_usage_calls": 0,
            "unpriced_calls": 0,
            "costs_by_currency": {},
            "by_model": {},
            "by_stage": {},
            "updated_at": datetime.now().isoformat(),
        }
        for record in records:
            usage = record.get("usage") or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            cached_input_tokens = int(usage.get("cached_input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
            summary["input_tokens"] += input_tokens
            summary["cached_input_tokens"] = summary.get("cached_input_tokens", 0) + cached_input_tokens
            summary["output_tokens"] += output_tokens
            summary["total_tokens"] += total_tokens
            if usage.get("estimated"):
                summary["estimated_calls"] += 1
            else:
                summary["provider_usage_calls"] += 1
            cost = record.get("cost")
            currency = record.get("currency") or "UNPRICED"
            if cost is None:
                summary["unpriced_calls"] += 1
            else:
                summary["costs_by_currency"][currency] = summary["costs_by_currency"].get(currency, 0.0) + float(cost)
            _add_bucket(
                summary["by_model"],
                record.get("model") or "unknown",
                input_tokens,
                cached_input_tokens,
                output_tokens,
                total_tokens,
                cost,
                currency,
            )
            _add_bucket(
                summary["by_stage"],
                record.get("stage") or "unknown",
                input_tokens,
                cached_input_tokens,
                output_tokens,
                total_tokens,
                cost,
                currency,
            )
        return summary


def record_current_agent_call(
    *,
    agent: Any,
    prompt: Any,
    response: Any,
    usage: Optional[Dict[str, Any]] = None,
    estimated: bool = True,
    stage: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    recorder = get_current_recorder()
    if recorder is None:
        return None
    return recorder.record_agent_call(
        agent=agent,
        prompt=prompt,
        response=response,
        stage=stage or get_current_stage(),
        usage=usage,
        estimated=estimated,
        metadata=metadata,
    )


def _add_bucket(
    buckets: Dict[str, Any],
    key: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cost: Any,
    currency: str,
) -> None:
    bucket = buckets.setdefault(
        str(key),
        {
            "calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "costs_by_currency": {},
            "unpriced_calls": 0,
        },
    )
    bucket["calls"] += 1
    bucket["input_tokens"] += input_tokens
    bucket["cached_input_tokens"] += cached_input_tokens
    bucket["output_tokens"] += output_tokens
    bucket["total_tokens"] += total_tokens
    if cost is None:
        bucket["unpriced_calls"] += 1
    else:
        bucket["costs_by_currency"][currency] = bucket["costs_by_currency"].get(currency, 0.0) + float(cost)


def _agent_primary_config(agent: Any) -> Dict[str, Any]:
    billing_config = getattr(agent, "billing_config", None)
    if isinstance(billing_config, dict) and billing_config:
        return dict(billing_config)
    config_list = getattr(getattr(agent, "llm_config", None), "get", lambda *_: None)("config_list")
    if isinstance(config_list, list) and config_list:
        return dict(config_list[0] or {})
    return {}


def _first_int(payload: Dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def _cached_input_tokens(payload: Dict[str, Any]) -> int:
    direct = _first_int(payload, "cached_input_tokens", "cached_prompt_tokens")
    if direct > 0:
        return direct
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else payload
    for details_key in ("input_tokens_details", "prompt_tokens_details"):
        details = raw.get(details_key) if isinstance(raw, dict) else None
        if isinstance(details, dict):
            cached = _first_int(details, "cached_tokens", "cached_input_tokens", "cached_prompt_tokens")
            if cached > 0:
                return cached
    return 0


def _usage_model(usage: Optional[Dict[str, Any]]) -> str:
    if not isinstance(usage, dict):
        return ""
    return str(usage.get("model") or "")


def _safe_base_url(value: Any) -> str:
    text = str(value or "")
    return text.rstrip("/")
