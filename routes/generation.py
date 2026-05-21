"""
生成任务相关路由
"""

import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from utils.response import success_response, error_response
from utils.task_identity import resolve_text_task_id
import logging

logger = logging.getLogger(__name__)
generation_bp = Blueprint('generation', __name__)

def register_generation_routes(app, generation_service, prd_service):
    """注册生成任务相关路由"""
    
    @app.route('/api/generation/tasks', methods=['GET'])
    def list_generation_tasks():
        """获取所有生成任务"""
        try:
            tasks = generation_service.list_tasks()
            return success_response({'tasks': tasks})
        except Exception as e:
            logger.error(f"获取生成任务列表失败: {str(e)}")
            return error_response(f"获取生成任务列表失败: {str(e)}")

    @app.route('/api/generation/tasks/<task_id>', methods=['GET'])
    def get_generation_task(task_id):
        """获取任务详情"""
        try:
            task_id = resolve_text_task_id(task_id)
            task = generation_service.get_task(task_id)
            if not task:
                return error_response('任务不存在', 404)
            
            return success_response(task)
        except Exception as e:
            logger.error(f"获取生成任务详情失败: {str(e)}")
            return error_response(f"获取生成任务详情失败: {str(e)}")

    @app.route('/api/generation/start', methods=['POST'])
    def start_generation():
        """兼容入口：文本PRD统一转到LangGraph运行服务。"""
        try:
            data = request.json
            if not data or 'prd_id' not in data:
                return error_response('缺少必要参数: prd_id', 400)
    
            prd_id = data.get('prd_id')
            prd = prd_service.get_prd(prd_id)
            
            if not prd:
                return error_response('PRD不存在', 404)

            from services.generation.langgraph_text_pipeline import LangGraphTextPipelineRuntimeService
            result = LangGraphTextPipelineRuntimeService().start_generation(prd_id)
            logger.info(f"通过兼容入口启动文本LangGraph任务: task={result.get('task_id')}, PRD={prd['name']}")

            return success_response({
                'task_id': result.get('task_id'),
                'status': 'running'
            })
        except Exception as e:
            logger.error(f"启动生成任务失败: {str(e)}")
            return error_response(f"启动生成任务失败: {str(e)}")

    @app.route('/api/generation/tasks/<task_id>/files', methods=['GET'])
    def get_task_files(task_id):
        """获取任务相关文件"""
        try:
            task_id = resolve_text_task_id(task_id)
            file_type = request.args.get('type')  # 可选参数，筛选文件类型
    
            files = generation_service.get_task_files(task_id, file_type)
    
            return success_response({'files': files})
        except Exception as e:
            logger.error(f"获取任务文件失败: {str(e)}")
            return error_response(f"获取任务文件失败: {str(e)}")

    @app.route('/api/generation/tasks/<task_id>/export', methods=['POST'])
    def export_task_file(task_id):
        """导出任务文件"""
        try:
            task_id = resolve_text_task_id(task_id)
            data = request.json
            if not data or 'file_type' not in data:
                return error_response('缺少必要参数: file_type', 400)
                
            file_type = data.get('file_type')
            
            # 支持的文件类型
            if file_type not in ['excel', 'json', 'md', 'html']:
                return error_response('不支持的文件类型', 400)
                
            # 导出文件
            file_path = generation_service.export_task_file(task_id, file_type)
            
            if not file_path or not os.path.exists(file_path):
                return error_response('导出文件失败', 500)
                
            # 设置下载名称
            filename = os.path.basename(file_path)
            
            return send_file(
                file_path,
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            logger.error(f"导出任务文件失败: {str(e)}")
            return error_response(f"导出任务文件失败: {str(e)}")

    @app.route('/api/tasks/<task_id>/start', methods=['POST'])
    def start_task(task_id):
        """旧AutoGen直接启动入口已停用。文本PRD请使用 /api/prds/<prd_id>/start-task。"""
        logger.warning(f"拒绝旧任务直接启动入口: task_id={task_id}")
        return error_response('旧任务直接启动入口已停用，请通过文本PRD或图片需求入口启动任务', 410)

    # 注册Blueprint
    app.register_blueprint(generation_bp, url_prefix='/api/generation')
    
    return app
