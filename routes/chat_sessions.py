"""自由会话模块 API 路由。"""

import logging

from flask import request

from services.chat.chat_session_service import ChatSessionService
from utils.response import error_response, success_response

logger = logging.getLogger(__name__)
chat_service = ChatSessionService()


def register_chat_session_routes(app):
    """注册会话模块路由。"""

    @app.route("/api/chat/sessions", methods=["GET"])
    def list_chat_sessions():
        try:
            limit = request.args.get("limit", 50, type=int)
            sessions = chat_service.list_sessions(limit=limit)
            return success_response({"sessions": sessions})
        except Exception as exc:
            logger.exception("获取会话列表失败")
            return error_response(f"获取会话列表失败: {exc}", 500)

    @app.route("/api/chat/sessions", methods=["POST"])
    def create_chat_session():
        try:
            payload = request.get_json(silent=True) or {}
            session = chat_service.create_session(title=payload.get("title"))
            return success_response(session, "会话已创建")
        except Exception as exc:
            logger.exception("创建会话失败")
            return error_response(f"创建会话失败: {exc}", 500)

    @app.route("/api/chat/sessions/<session_id>", methods=["DELETE"])
    def delete_chat_session(session_id):
        try:
            if not chat_service.delete_session(session_id):
                return error_response("会话不存在", 404)
            return success_response(None, "会话已删除")
        except Exception as exc:
            logger.exception("删除会话失败")
            return error_response(f"删除会话失败: {exc}", 500)

    @app.route("/api/chat/sessions/<session_id>/messages", methods=["GET"])
    def get_chat_messages(session_id):
        try:
            messages = chat_service.get_messages(session_id)
            return success_response({"messages": messages})
        except ValueError as exc:
            return error_response(str(exc), 404)
        except Exception as exc:
            logger.exception("获取消息失败")
            return error_response(f"获取消息失败: {exc}", 500)

    @app.route("/api/chat/sessions/<session_id>/messages", methods=["POST"])
    def send_chat_message(session_id):
        try:
            payload = request.get_json(silent=True) or {}
            content = payload.get("content") or payload.get("message") or ""
            result = chat_service.send_message(session_id, content)
            return success_response(result)
        except ValueError as exc:
            return error_response(str(exc), 400)
        except Exception as exc:
            logger.exception("发送消息失败")
            return error_response(f"发送消息失败: {exc}", 500)
