"""
统一任务管理API路由
根据 UI_REDESIGN_PLAN_A.md 设计文档实现
"""
import logging
from flask import Blueprint, request, jsonify
from utils.response import success_response, error_response
from services.tasks.task_unified_service import TaskUnifiedService

logger = logging.getLogger(__name__)

# 创建蓝图
tasks_unified_bp = Blueprint('tasks_unified', __name__)


def register_tasks_unified_routes(app, task_unified_service: TaskUnifiedService):
    """注册统一任务管理路由"""
    
    @app.route('/api/tasks/unified', methods=['GET'])
    def list_unified_tasks():
        """
        统一任务列表查询
        
        Query参数：
        - group: 状态分组筛选 (draft/pending/processing/waiting/completed/failed/all)
        - type: 任务类型筛选 (image/text/all)
        - status: 具体状态筛选
        - start_date: 开始时间
        - end_date: 结束时间
        - keyword: 搜索关键词
        - page: 页码 (默认1)
        - page_size: 每页数量 (默认20)
        
        返回：
        {
          "success": true,
          "data": {
            "tasks": [...],
            "total": 128,
            "group_counts": {
              "draft": 3,
              "pending": 2,
              "processing": 3,
              "waiting": 2,
              "completed": 20,
              "failed": 1
            }
          }
        }
        """
        try:
            # 获取查询参数
            status_group = request.args.get('group')
            task_type = request.args.get('type', 'all')
            status = request.args.get('status')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            keyword = request.args.get('keyword')
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
            
            # 调用服务
            result = task_unified_service.list_tasks(
                status_group=status_group,
                task_type=task_type,
                status=status,
                start_date=start_date,
                end_date=end_date,
                keyword=keyword,
                page=page,
                page_size=page_size
            )
            
            logger.info(f"统一任务列表查询成功: 总数={result['total']}, 当前页={len(result['tasks'])}")
            
            return success_response(result)
            
        except Exception as e:
            logger.error(f"统一任务列表查询失败: {str(e)}", exc_info=True)
            return error_response(f"查询失败: {str(e)}", 500)
    
    @app.route('/api/tasks/unified/dashboard', methods=['GET'])
    def get_dashboard_stats():
        """
        获取工作台统计数据
        
        返回：
        {
          "success": true,
          "data": {
            "total_tasks": 128,
            "processing_tasks": 5,
            "waiting_confirmation": 2,
            "completed_today": 3,
            "recent_tasks": [...]
          }
        }
        """
        try:
            stats = task_unified_service.get_dashboard_stats()
            
            logger.info(f"工作台统计查询成功: 总任务数={stats['total_tasks']}")
            
            return success_response(stats)
            
        except Exception as e:
            logger.error(f"工作台统计查询失败: {str(e)}", exc_info=True)
            return error_response(f"查询失败: {str(e)}", 500)
    
    @app.route('/api/tasks/unified/<task_id>/history', methods=['GET'])
    def get_task_history(task_id):
        """
        获取任务的历史运行记录
        
        Query参数：
        - type: 任务类型（text/image）
        
        返回：
        {
          "success": true,
          "data": {
            "history": [
              {
                "task_id": "task_xxx",
                "status": "completed",
                "status_display": "✅ 已完成",
                "created_at": "2025-10-27T10:00:00",
                "updated_at": "2025-10-27T10:30:00",
                "completion_percentage": 100,
                "message": "生成成功"
              }
            ],
            "total": 3
          }
        }
        """
        try:
            task_type = request.args.get('type', 'text')
            
            result = task_unified_service.get_task_history(task_id, task_type)
            
            logger.info(f"任务历史记录查询成功: task_id={task_id}, type={task_type}, total={result['total']}")
            
            return success_response(result)
            
        except Exception as e:
            logger.error(f"任务历史记录查询失败: {str(e)}", exc_info=True)
            return error_response(f"获取历史记录失败: {str(e)}", 500)
    
    @app.route('/api/tasks/unified/<task_id>/detail', methods=['GET'])
    def get_unified_task_detail(task_id):
        """
        获取统一任务详情
        
        根据task_id的前缀判断任务类型：
        - req_mod_* -> 图片需求任务
        - uuid -> 文本PRD任务
        
        返回：
        {
          "success": true,
          "data": {
            "task": {...},  # TaskViewModel
            "source": {...}  # 原始数据
          }
        }
        """
        try:
            # 根据ID前缀判断类型
            if task_id.startswith('req_mod_'):
                # 图片需求任务 - 待实现详情接口
                return error_response('图片需求任务详情接口待实现', 501)
            else:
                # 文本PRD任务 - 待实现详情接口
                return error_response('文本PRD任务详情接口待实现', 501)
            
        except Exception as e:
            logger.error(f"任务详情查询失败: {str(e)}", exc_info=True)
            return error_response(f"查询失败: {str(e)}", 500)
    
    # 注册蓝图
    app.register_blueprint(tasks_unified_bp, url_prefix='/api/tasks/unified')
    
    logger.info("统一任务管理路由注册完成")
    
    return app
