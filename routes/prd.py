"""
PRD相关路由（重构版）
"""
import os
import logging
from datetime import datetime
from flask import Blueprint, request, send_file
from utils.response import success_response, error_response
from database.models import Task, TaskStatus
from database.task_manager import SQLiteTaskManager

logger = logging.getLogger(__name__)
prd_bp = Blueprint('prd', __name__)
task_manager = SQLiteTaskManager(logger=logger)

def register_prd_routes(app, prd_service, generation_service):
    """注册PRD相关路由"""
    
    # ========== PRD管理API ==========
    
    @app.route('/api/prds/upload', methods=['POST'], endpoint='upload_text_prd')
    def upload_text_prd():
        """
        上传PRD文档
        请求体：{"name": "...", "content": "..."}
        返回：{"success": true, "prd_id": "..."}
        """
        try:
            data = request.json
            if not data or 'content' not in data:
                return error_response('缺少必要参数: content', 400)
            
            content = data.get('content')
            name = data.get('name', f"PRD_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
            
            # 创建PRD（草稿状态）
            prd_id = prd_service.create_prd(name, content)
            
            logger.info(f"上传PRD成功: {name} (ID: {prd_id})")
            
            return success_response({
                'prd_id': prd_id,
                'name': name,
                'status': 'draft'
            })
            
        except Exception as e:
            logger.error(f"上传PRD失败: {str(e)}")
            return error_response(f"上传PRD失败: {str(e)}", 500)
    
    @app.route('/api/prds', methods=['GET'])
    def list_prds():
        """
        获取PRD列表
        查询参数：status, limit, offset
        返回：{"success": true, "prds": [...], "total": int}
        """
        try:
            status = request.args.get('status')
            limit = int(request.args.get('limit', 50))
            offset = int(request.args.get('offset', 0))
            
            result = prd_service.list_prds(status=status, limit=limit, offset=offset)
            
            return success_response(result)
            
        except Exception as e:
            logger.error(f"获取PRD列表失败: {str(e)}")
            return error_response(f"获取PRD列表失败: {str(e)}", 500)
    
    @app.route('/api/prds/<prd_id>', methods=['GET'])
    def get_prd(prd_id):
        """
        获取PRD详情
        返回：{"success": true, "prd": {...}}
        """
        try:
            prd = prd_service.get_prd(prd_id)
            
            if not prd:
                return error_response('PRD不存在', 404)
            
            return success_response({'prd': prd})
            
        except Exception as e:
            logger.error(f"获取PRD详情失败: {str(e)}")
            return error_response(f"获取PRD详情失败: {str(e)}", 500)
    
    @app.route('/api/prds/<prd_id>', methods=['PUT'])
    def update_prd(prd_id):
        """
        更新PRD（内容、名称等）
        请求体：{"content": "...", "name": "...", "business": "...", "description": "..."}
        返回：{"success": true, "message": "更新成功"}
        """
        try:
            data = request.json
            
            if not data:
                return error_response('缺少请求数据', 400)
            
            # 更新PRD
            success = prd_service.update_prd(prd_id, **data)
            
            if not success:
                return error_response('PRD不存在或更新失败', 404)
            
            logger.info(f"更新PRD成功: {prd_id}")
            
            return success_response({'message': '更新成功'})
            
        except Exception as e:
            logger.error(f"更新PRD失败: {str(e)}")
            return error_response(f"更新PRD失败: {str(e)}", 500)
    
    @app.route('/api/prds/<prd_id>', methods=['DELETE'])
    def delete_prd(prd_id):
        """
        删除PRD
        返回：{"success": true, "message": "删除成功"}
        """
        try:
            success = prd_service.delete_prd(prd_id)
            
            if not success:
                return error_response('PRD不存在或删除失败', 404)
            
            logger.info(f"删除PRD成功: {prd_id}")
            
            return success_response({'message': '删除成功'})
            
        except Exception as e:
            logger.error(f"删除PRD失败: {str(e)}")
            return error_response(f"删除PRD失败: {str(e)}", 500)
    
    # ========== 任务启动API ==========
    
    @app.route('/api/prds/<prd_id>/start-task', methods=['POST'])
    def start_prd_task(prd_id):
        """
        启动PRD生成任务
        请求体：{}
        返回：{"success": true, "task_id": "..."}
        """
        try:
            # 获取PRD
            prd = prd_service.get_prd(prd_id)

            if not prd:
                return error_response('PRD不存在', 404)

            # 🔒 检查是否有其他任务正在运行（系统限制：单任务运行）
            from utils.task_check import check_running_tasks
            running_task = check_running_tasks()
            if running_task:
                task_name = running_task.get('name', '未知')
                error_message = f"启动失败：任务 \"{task_name}\" 正在运行中，请稍后重试。"
                return error_response(error_message, code=409)

            # 检查任务是否真的在运行
            # 如果有关联的Task，需要检查Task的实际状态
            if prd.get('generated_task_id'):
                task = task_manager.get_task(prd['generated_task_id'])
                if task:
                    # 只有Task真正在运行中或等待确认时才拦截
                    task_status = task.get('status', '')
                    if task_status in ['processing', 'running', 'analyzing', 'collaborating',
                                      'pm_responding', 'checking_intervention', 'waiting_confirmation',
                                      'finalizing_prd', 'generating_testcases', 'writing_testcases']:
                        return error_response('任务正在运行中，无法重新启动', 400)
                    # Task是终态（completed/failed/cancelled），允许启动
                    logger.info(f"Task {prd['generated_task_id']} 状态为 {task_status}，允许重新启动")

            from services.generation.langgraph_text_pipeline import LangGraphTextPipelineRuntimeService
            result = LangGraphTextPipelineRuntimeService().start_generation(prd_id)
            logger.info(f"启动PRD任务（LangGraph）: PRD={prd_id}, Task={result.get('task_id')}")
            return success_response({
                'task_id': result.get('task_id'),
                'message': result.get('message', '任务已启动，使用LangGraph文本流程')
            })

        except Exception as e:
            logger.error(f"启动PRD任务失败: {str(e)}")
            return error_response(f"启动PRD任务失败: {str(e)}", 500)
    
    @app.route('/api/prds/<prd_id>/download', methods=['GET'])
    def download_prd(prd_id):
        """
        下载PRD文档
        返回：Markdown文件
        """
        try:
            prd = prd_service.get_prd(prd_id)
            
            if not prd:
                return error_response('PRD不存在', 404)
            
            # 确保文件存在
            file_path = prd.get('file_path')
            if not file_path or not os.path.exists(file_path):
                return error_response('PRD文件不存在', 404)
            
            return send_file(
                file_path,
                mimetype='text/markdown',
                as_attachment=True,
                download_name=f"{prd['name']}.md"
            )
            
        except Exception as e:
            logger.error(f"下载PRD失败: {str(e)}")
            return error_response(f"下载PRD失败: {str(e)}", 500)
    
    # 注册Blueprint
    app.register_blueprint(prd_bp, url_prefix='/api/prd')
    
    return app
