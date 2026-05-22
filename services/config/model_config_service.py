"""Runtime model configuration service."""

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import httpx

from services.config.pricing import parse_optional_float
from services.generation.structured_testcase_pipeline import StructuredTestcasePipeline


MODEL_TYPE_META = {
    "split": {
        "label": "需求拆分模型",
        "description": "推荐 GPT-5.5，用于 PRD 分块、LU 拆分和链路识别。",
    },
    "requirement": {
        "label": "需求/测试用例模型",
        "description": "推荐 DeepSeek V4 Pro，用于 PRD 审查、确认整合、最终 PRD 和测试用例生成。",
    },
    "vision": {
        "label": "图片分析模型",
        "description": "推荐 Doubao Seed 2.0 Pro，用于图片、标注、箭头备注和文件名语义提取。",
    },
}

DEFAULT_MODEL_TYPES = ["split", "requirement", "vision"]
MODEL_TYPE_ALIASES = {
    "text": "requirement",
    "testcase": "requirement",
}
SECRET_PLACEHOLDERS = {"", "******", "********", None}


class ModelConfigService:
    """Read, write and validate OAI_CONFIG_LIST with UI-safe masking."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or get_model_config_path()

    def get_public_config(self) -> Dict[str, Any]:
        configs = self.load_config()
        public_configs = self._collapse_public_configs(configs)
        return {
            "config_path": self.config_path,
            "updated_at": self._get_updated_at(),
            "model_types": [
                {"type": model_type, **MODEL_TYPE_META[model_type]}
                for model_type in DEFAULT_MODEL_TYPES
            ],
            "models": [
                self._to_public_config(config, config.get("_source_index", index))
                for index, config in enumerate(public_configs)
            ],
        }

    def load_config(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.config_path):
            return []
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("模型配置文件必须是 JSON 数组")
        return [item for item in data if isinstance(item, dict)]

    def save_public_config(self, models: Any) -> Dict[str, Any]:
        if not isinstance(models, list):
            raise ValueError("models 必须是数组")
        existing = self.load_config()
        normalized = [
            self._normalize_public_config(raw_config, index, existing)
            for index, raw_config in enumerate(models)
        ]
        self._write_config(normalized)
        return self.get_public_config()

    def test_config(self, raw_config: Dict[str, Any]) -> Dict[str, Any]:
        config = self._normalize_public_config(raw_config, 0, self.load_config())
        if not config.get("enabled", True):
            raise ValueError("当前模型配置未启用")
        api_key = str(config.get("api_key") or "").strip()
        base_url = str(config.get("base_url") or "").rstrip("/")
        model = str(config.get("model") or "").strip()
        if not api_key or not base_url or not model:
            raise ValueError("api_key、base_url、model 不能为空")

        started = time.time()
        if config.get("api") == "openai-responses":
            text = self._test_openai_responses(config)
        else:
            text = self._test_chat_completions(config)
        return {
            "ok": True,
            "model": model,
            "latency_ms": int((time.time() - started) * 1000),
            "response_preview": str(text or "")[:200],
        }

    def _test_openai_responses(self, config: Dict[str, Any]) -> str:
        pipeline = StructuredTestcasePipeline()
        base_url = str(config.get("base_url")).rstrip("/")
        url = f"{base_url}/responses" if not base_url.endswith("/responses") else base_url
        result = pipeline._post_openai_responses_stream(
            url=url,
            api_key=str(config.get("api_key")),
            body={
                "model": config.get("model"),
                "stream": True,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "只回复 OK"}],
                    }
                ],
            },
        )
        if isinstance(result, dict):
            return str(result.get("text") or "")
        return str(result or "")

    @staticmethod
    def _test_chat_completions(config: Dict[str, Any]) -> str:
        body = {
            "model": config.get("model"),
            "messages": [{"role": "user", "content": "只回复 OK"}],
            "temperature": 0,
            "max_tokens": 16,
        }
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(
                f"{str(config.get('base_url')).rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.get('api_key')}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return str(message.get("content") or "")

    def _normalize_public_config(
        self,
        raw_config: Dict[str, Any],
        index: int,
        existing_configs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(raw_config, dict):
            raise ValueError(f"第 {index + 1} 条模型配置不是对象")
        model_type = self._canonical_model_type(raw_config.get("model_type") or "requirement")
        if model_type not in MODEL_TYPE_META:
            raise ValueError(f"不支持的模型类型: {model_type}")

        config = dict(raw_config)
        config["model_type"] = model_type
        config["model"] = str(config.get("model") or "").strip()
        config["base_url"] = str(config.get("base_url") or "").strip().rstrip("/")
        config["enabled"] = config.get("enabled") is not False
        if not config["model"]:
            raise ValueError(f"{MODEL_TYPE_META[model_type]['label']} model 不能为空")
        if not config["base_url"]:
            raise ValueError(f"{MODEL_TYPE_META[model_type]['label']} base_url 不能为空")

        api_key = config.get("api_key")
        if api_key in SECRET_PLACEHOLDERS:
            api_key = self._find_existing_api_key(config, index, existing_configs)
        config["api_key"] = str(api_key or "").strip()
        if not config["api_key"]:
            raise ValueError(f"{MODEL_TYPE_META[model_type]['label']} api_key 不能为空")

        name = str(config.get("name") or MODEL_TYPE_META[model_type]["label"]).strip()
        config["name"] = name
        self._normalize_pricing(config)
        config.pop("api_key_masked", None)
        config.pop("id", None)
        config.pop("testing", None)
        return {
            key: value
            for key, value in config.items()
            if value is not None and value != "" and key != "_source_index"
        }

    @staticmethod
    def _canonical_model_type(model_type: Any) -> str:
        normalized = str(model_type or "requirement").strip()
        return MODEL_TYPE_ALIASES.get(normalized, normalized)

    def _collapse_public_configs(self, configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_type: Dict[str, Dict[str, Any]] = {}
        for index, raw_config in enumerate(configs):
            if not isinstance(raw_config, dict):
                continue
            model_type = self._canonical_model_type(raw_config.get("model_type") or "requirement")
            if model_type not in MODEL_TYPE_META:
                continue

            config = dict(raw_config)
            config["model_type"] = model_type
            config["_source_index"] = index
            if model_type == "requirement":
                config["name"] = MODEL_TYPE_META["requirement"]["label"]

            existing = by_type.get(model_type)
            if not existing:
                by_type[model_type] = config
                continue
            if existing.get("enabled") is False and config.get("enabled") is not False:
                by_type[model_type] = config

        return [by_type[model_type] for model_type in DEFAULT_MODEL_TYPES if model_type in by_type]

    @staticmethod
    def _find_existing_api_key(
        config: Dict[str, Any],
        index: int,
        existing_configs: List[Dict[str, Any]],
    ) -> str:
        config_id = str(config.get("id") or "").strip()
        if config_id.startswith("config-"):
            try:
                original_index = int(config_id.split("-", 1)[1])
                if 0 <= original_index < len(existing_configs):
                    return str(existing_configs[original_index].get("api_key") or "")
            except Exception:
                pass
        if index < len(existing_configs):
            return str(existing_configs[index].get("api_key") or "")
        return ""

    def _write_config(self, configs: List[Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.config_path)), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".OAI_CONFIG_LIST.",
            dir=os.path.dirname(os.path.abspath(self.config_path)),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(configs, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(temp_path, self.config_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _to_public_config(self, config: Dict[str, Any], index: int) -> Dict[str, Any]:
        public_config = dict(config)
        public_config.pop("_source_index", None)
        api_key = str(public_config.pop("api_key", "") or "")
        public_config["id"] = f"config-{index}"
        public_config["api_key"] = "******" if api_key else ""
        public_config["api_key_masked"] = mask_secret(api_key)
        public_config.setdefault("enabled", True)
        public_config["model_type"] = self._canonical_model_type(public_config.get("model_type") or "requirement")
        public_config.setdefault("name", MODEL_TYPE_META.get(public_config["model_type"], {}).get("label", "模型配置"))
        public_config.setdefault("currency", "CNY")
        return public_config

    def _get_updated_at(self) -> str:
        if not os.path.exists(self.config_path):
            return ""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(self.config_path)))

    @staticmethod
    def _normalize_pricing(config: Dict[str, Any]) -> None:
        input_price = parse_optional_float(config.get("input_price_per_million"))
        cached_input_price = parse_optional_float(config.get("cached_input_price_per_million"))
        output_price = parse_optional_float(config.get("output_price_per_million"))
        if input_price is not None and input_price < 0:
            raise ValueError("输入单价不能为负数")
        if cached_input_price is not None and cached_input_price < 0:
            raise ValueError("缓存输入单价不能为负数")
        if output_price is not None and output_price < 0:
            raise ValueError("输出单价不能为负数")
        if input_price is None:
            config.pop("input_price_per_million", None)
        else:
            config["input_price_per_million"] = input_price
        if cached_input_price is None:
            config.pop("cached_input_price_per_million", None)
        else:
            config["cached_input_price_per_million"] = cached_input_price
        if output_price is None:
            config.pop("output_price_per_million", None)
        else:
            config["output_price_per_million"] = output_price
        currency = str(config.get("currency") or "CNY").strip().upper()
        config["currency"] = currency or "CNY"
        pricing_note = str(config.get("pricing_note") or "").strip()
        if pricing_note:
            config["pricing_note"] = pricing_note
        else:
            config.pop("pricing_note", None)


def get_model_config_path() -> str:
    config_path = os.environ.get("AUTOGEN_CONFIG_PATH")
    if config_path:
        return config_path
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(project_root, "config", "OAI_CONFIG_LIST")


def load_model_config() -> List[Dict[str, Any]]:
    return ModelConfigService().load_config()


def mask_secret(secret: str) -> str:
    text = str(secret or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}{'*' * 8}{text[-4:]}"
