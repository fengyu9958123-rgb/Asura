"""
Autogen Web API服务

HTTP-only模式，轮询获取状态和消息
"""

import os
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template

from config import Config
from services.core.agent_service import AgentService
from services.notifications.logging_service import LoggingService
from services.notifications.notification_service import NotificationService
# from database.task_manager import SQLiteTaskManager as TaskManager  # 已移动到services模块
from services.storage.file_service import FileService
from services.core.generation_service import SimplifiedGenerationService
from services.prd.prd_service import PRDService
from services.tasks.task_unified_service import TaskUnifiedService
from database.models import DatabaseManager
from routes.prd import register_prd_routes
from routes.generation import register_generation_routes
from routes.confirmation import register_confirmation_routes
from routes.tasks import register_task_routes
from routes.files import register_files_routes
from routes.testcases import testcases_bp
from routes.requirement_modules import register_requirement_module_routes
from routes.tasks_unified import register_tasks_unified_routes
from routes.image_pipeline import image_pipeline_bp
from routes.settings import register_settings_routes
from routes.chat_sessions import register_chat_session_routes
from utils.response import success_response, error_response

LOG_DIR = os.environ.get('LOG_DIR', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
APP_LOG_FILE = os.environ.get('APP_LOG_FILE', os.path.join(LOG_DIR, 'app.log'))

# 创建日志记录器
logging.basicConfig(
    level=getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(APP_LOG_FILE)
    ]
)

logger = logging.getLogger(__name__)


def create_app(config_obj=None):
    """创建Flask应用"""

    # 创建应用实例
    app = Flask(__name__, static_folder='static', static_url_path='/static')

    # 使用配置对象
    if config_obj is None:
        config_obj = Config()
    app.config.from_object(config_obj)

    # 确保必要的目录结构存在
    ensure_directories_exist(app)

    # 初始化服务
    logging_service = LoggingService()
    notification_service = NotificationService(logger=logging_service)
    file_service = FileService(app.config['UPLOAD_FOLDER'], logging_service)
    from database.task_manager import SQLiteTaskManager
    task_manager = SQLiteTaskManager(logger=logging_service)
    agent_service = AgentService(logging_service)

    # 初始化数据库管理器和服务
    db_manager = DatabaseManager()
    db_manager.initialize()
    try:
        from database.init_db import DatabaseInitializer
        DatabaseInitializer.create_sample_data()
    except Exception as exc:
        logger.warning(f"初始化示例数据失败: {exc}")

    prd_service = PRDService(
        db_manager=db_manager,
        upload_folder=app.config.get('UPLOAD_FOLDER', 'uploads')
    )

    # 初始化统一任务服务
    task_unified_service = TaskUnifiedService(db_manager=db_manager)
    logger.info("TaskUnifiedService initialized successfully")

    # 创建空的socketio对象用于兼容
    class DummySocketIO:
        def emit(self, *args, **kwargs):
            pass  # 不执行任何操作的emit方法
    dummy_socketio = DummySocketIO()

    generation_service = SimplifiedGenerationService(
        agent_service=agent_service,
        logging_service=logging_service,
        file_service=file_service,
        socketio=dummy_socketio
    )

    # 将task_manager绑定到agent_service，用于消息记录
    agent_service.task_manager = task_manager

    # 注册路由
    register_prd_routes(app, prd_service, generation_service)
    register_generation_routes(app, generation_service, prd_service)
    register_files_routes(app, file_service, generation_service)
    register_confirmation_routes(app, generation_service, task_manager)
    register_task_routes(app, task_manager, generation_service)
    register_settings_routes(app)
    register_chat_session_routes(app)
    logger.info("会话模块路由注册完成")

    # 注册测试用例蓝图
    app.register_blueprint(testcases_bp)

    # 注册需求模块路由（阶段1）
    register_requirement_module_routes(app)

    # 注册统一任务管理路由（新增 - Phase 1）
    register_tasks_unified_routes(app, task_unified_service)
    logger.info("统一任务管理路由注册完成")

    # 注册图片流程路由（新增 - 图片生成测试用例）
    app.register_blueprint(image_pipeline_bp)
    logger.info("图片流程路由注册完成")

    # 添加静态文件路由
    @app.route('/')
    def index():
        from app_config import SHOW_AI_COLLABORATION
        return render_template('vue_client_improved.html',
                             show_ai_collaboration=SHOW_AI_COLLABORATION)

    @app.route('/improved')
    def vue_client_improved():
        from app_config import SHOW_AI_COLLABORATION
        return render_template('vue_client_improved.html',
                             show_ai_collaboration=SHOW_AI_COLLABORATION)

    @app.route('/api/status')
    def status():
        return success_response({'status': 'running'})

    # 提供outputs目录的静态文件访问（用于图片等）
    @app.route('/outputs/<path:filename>')
    def serve_outputs(filename):
        """提供outputs目录下的文件访问（已加固：防止路径遍历攻击）"""
        from flask import send_from_directory, abort
        from utils.security import get_safe_path, is_safe_path

        # 定义允许访问的基础目录
        outputs_dir = os.path.abspath('outputs')

        # 安全检查：验证请求的路径在 outputs 目录内
        if not is_safe_path(outputs_dir, filename):
            logger.warning(f"路径遍历攻击尝试被阻止: {repr(filename)}")
            abort(403)  # 禁止访问

        # 获取安全路径
        safe_path = get_safe_path(outputs_dir, filename)
        if safe_path is None:
            logger.warning(f"无效的文件路径请求: {repr(filename)}")
            abort(400)  # 错误请求

        # 检查文件是否存在
        if not os.path.isfile(safe_path):
            abort(404)  # 文件不存在

        # 使用 send_from_directory 安全地发送文件
        return send_from_directory(outputs_dir, filename)

    # 全局错误处理
    @app.errorhandler(404)
    def page_not_found(e):
        return error_response('资源不存在', 404)

    @app.errorhandler(500)
    def internal_server_error(e):
        return error_response('服务器内部错误', 500)

    return app


def ensure_directories_exist(app):
    """确保所有必要的目录结构存在"""
    directories = [
        app.config['UPLOAD_FOLDER'],  # 上传文件夹
        'data/tasks',                 # 任务数据
        'outputs/excel',              # Excel输出
        'outputs/html',               # HTML输出
        'outputs/raw',                # 原始数据
        'logs',                       # 日志文件夹
        'static/libs'                 # 本地库文件夹
    ]

    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                logger.info(f"创建目录: {directory}")
            except Exception as e:
                logger.error(f"创建目录失败 {directory}: {e}")


app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5002, debug=True)
