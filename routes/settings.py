"""Settings API routes."""

import logging
from flask import request

from services.config.model_config_service import ModelConfigService
from utils.response import success_response, error_response

logger = logging.getLogger(__name__)


def register_settings_routes(app):
    """Register runtime settings routes."""

    @app.route("/api/settings/models", methods=["GET"])
    def get_model_settings():
        try:
            return success_response(ModelConfigService().get_public_config())
        except Exception as exc:
            logger.exception("获取模型配置失败")
            return error_response(f"获取模型配置失败: {exc}", 500)

    @app.route("/api/settings/models", methods=["PUT"])
    def update_model_settings():
        try:
            payload = request.get_json(silent=True) or {}
            result = ModelConfigService().save_public_config(payload.get("models"))
            return success_response(result, "模型配置已保存")
        except Exception as exc:
            logger.exception("保存模型配置失败")
            return error_response(f"保存模型配置失败: {exc}", 400)

    @app.route("/api/settings/models/test", methods=["POST"])
    def test_model_settings():
        try:
            payload = request.get_json(silent=True) or {}
            result = ModelConfigService().test_config(payload.get("model") or payload)
            return success_response(result, "模型连接测试成功")
        except Exception as exc:
            logger.exception("模型连接测试失败")
            return error_response(f"模型连接测试失败: {exc}", 400)
