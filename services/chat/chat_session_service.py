"""自由会话服务 — 豆包式多轮对话，使用已配置的模型。"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from database.models import ChatMessage, ChatSession, db_manager
from services.config.model_config_service import ModelConfigService
from services.generation.llm_response_cleaner import strip_model_reasoning

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """你是 AIcase 的智能助手，面向 QA、测试开发、产品和研发人员。
你可以帮助用户：
- 理解和梳理 PRD、需求文档
- 讨论测试策略、测试用例设计思路
- 解答软件测试、质量保障相关问题
- 对测试用例、缺陷分析给出建议

回答请清晰、结构化，必要时使用 Markdown。不要编造用户未提供的业务事实。"""

TITLE_MAX_LEN = 40


class ChatSessionService:
    """会话 CRUD 与 LLM 对话。"""

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        session = db_manager.get_session()
        try:
            rows = (
                session.query(ChatSession)
                .order_by(ChatSession.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [row.to_dict() for row in rows]
        finally:
            session.close()

    def create_session(self, title: Optional[str] = None) -> Dict[str, Any]:
        session = db_manager.get_session()
        try:
            row = ChatSession(
                id=str(uuid.uuid4()),
                title=(title or "新对话").strip() or "新对话",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.to_dict()
        finally:
            session.close()

    def delete_session(self, session_id: str) -> bool:
        session = db_manager.get_session()
        try:
            row = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not row:
                return False
            session.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        session = db_manager.get_session()
        try:
            if not session.query(ChatSession).filter(ChatSession.id == session_id).first():
                raise ValueError("会话不存在")
            rows = (
                session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
                .all()
            )
            return [row.to_dict() for row in rows if row.role in ("user", "assistant")]
        finally:
            session.close()

    def send_message(self, session_id: str, content: str) -> Dict[str, Any]:
        text = (content or "").strip()
        if not text:
            raise ValueError("消息内容不能为空")

        db = db_manager.get_session()
        try:
            chat_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not chat_session:
                raise ValueError("会话不存在")

            history = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
                .all()
            )
            llm_messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
            for msg in history:
                if msg.role in ("user", "assistant"):
                    llm_messages.append({"role": msg.role, "content": msg.content})
            llm_messages.append({"role": "user", "content": text})

            user_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="user",
                content=text,
            )
            db.add(user_msg)

            model_config = self._resolve_chat_model_config()
            assistant_text = self._call_chat_completions(model_config, llm_messages)

            assistant_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=assistant_text,
            )
            db.add(assistant_msg)

            if chat_session.title == "新对话" or not chat_session.title:
                chat_session.title = self._title_from_message(text)

            chat_session.model_name = str(model_config.get("model") or "")
            chat_session.updated_at = datetime.utcnow()

            db.commit()
            db.refresh(user_msg)
            db.refresh(assistant_msg)
            db.refresh(chat_session)

            return {
                "session": chat_session.to_dict(),
                "user_message": user_msg.to_dict(),
                "assistant_message": assistant_msg.to_dict(),
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _title_from_message(text: str) -> str:
        one_line = " ".join(text.split())
        if len(one_line) <= TITLE_MAX_LEN:
            return one_line or "新对话"
        return one_line[:TITLE_MAX_LEN] + "…"

    def _resolve_chat_model_config(self) -> Dict[str, Any]:
        configs = ModelConfigService().load_config()
        enabled = [c for c in configs if c.get("enabled", True)]
        for config in enabled:
            if str(config.get("model_type") or "").strip() == "chat":
                return self._validate_config(config)
        raise ValueError(
            "请先在「模型配置」中配置并启用「会话模型」（model_type: chat）"
        )

    @staticmethod
    def _validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
        api_key = str(config.get("api_key") or "").strip()
        base_url = str(config.get("base_url") or "").strip().rstrip("/")
        model = str(config.get("model") or "").strip()
        if not api_key or not base_url or not model:
            raise ValueError("模型配置不完整，请检查 api_key、base_url 和 model")
        return config

    def _call_chat_completions(
        self,
        config: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> str:
        if config.get("api") == "openai-responses":
            return self._call_openai_responses(config, messages)

        body = {
            "model": config.get("model"),
            "messages": messages,
            "temperature": float(config.get("temperature") or 0.7),
        }
        max_tokens = config.get("max_tokens")
        if max_tokens:
            body["max_tokens"] = int(max_tokens)

        url = f"{str(config.get('base_url')).rstrip('/')}/chat/completions"
        with httpx.Client(timeout=120, trust_env=False) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {config.get('api_key')}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"模型请求失败 HTTP {response.status_code}: {response.text[:800]}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        return strip_model_reasoning(str(content).strip())

    def _call_openai_responses(
        self,
        config: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> str:
        from services.generation.structured_testcase_pipeline import StructuredTestcasePipeline

        pipeline = StructuredTestcasePipeline()
        base_url = str(config.get("base_url")).rstrip("/")
        url = f"{base_url}/responses" if not base_url.endswith("/responses") else base_url

        input_items = []
        for msg in messages:
            role = msg.get("role") or "user"
            if role == "system":
                input_items.append({
                    "role": "user",
                    "content": [{"type": "input_text", "text": f"[系统指令]\n{msg.get('content', '')}"}],
                })
            else:
                input_items.append({
                    "role": role if role in ("user", "assistant") else "user",
                    "content": [{"type": "input_text", "text": msg.get("content", "")}],
                })

        result = pipeline._post_openai_responses_stream(
            url=url,
            api_key=str(config.get("api_key")),
            body={"model": config.get("model"), "stream": True, "input": input_items},
        )
        if isinstance(result, dict):
            text = str(result.get("text") or "")
        else:
            text = str(result or "")
        return strip_model_reasoning(text.strip())
