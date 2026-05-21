"""
任务检查工具 - 用于检查系统中是否有正在运行的任务
系统限制：同一时间只能运行一个任务
"""
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def check_running_tasks() -> Optional[Dict]:
    """
    检查系统中是否有正在运行的任务
    
    Returns:
        如果有运行中的任务，返回任务信息字典：
        {
            'id': str,           # 任务ID
            'name': str,         # 任务名称
            'type': str,         # 任务类型：'image' 或 'text'
            'status': str,       # 任务状态
            'progress': int      # 进度百分比
        }
        如果没有运行中的任务，返回 None
    """
    try:
        from database.models import RequirementModule, PRD, Task, db_manager
        
        session = db_manager.get_session()
        
        try:
            # 1. 检查图片任务（RequirementModule表）
            # 运行中的状态：processing；waiting_confirmation 虽暂停等待用户，但仍占用当前任务链路。
            image_task = session.query(RequirementModule).filter(
                RequirementModule.status.in_(['processing', 'waiting_confirmation'])
            ).first()
            
            if image_task:
                # 获取任务名称（兼容不同字段名）
                task_name = getattr(image_task, 'version_name', None) or \
                           getattr(image_task, 'name', None) or \
                           '未命名图片任务'

                return {
                    'id': image_task.id,
                    'name': task_name,
                    'type': 'image',
                    'status': image_task.status,
                    'progress': image_task.progress or 0
                }
            
            # 2. 检查文本PRD任务（PRD表）
            # 运行中的状态：processing
            text_prd = session.query(PRD).filter(
                PRD.status == 'processing'
            ).first()
            
            if text_prd:
                # 获取关联的Task以获取更详细的状态
                task_id = text_prd.generated_task_id
                task_name = text_prd.name or '未命名文本任务'
                task_progress = 0
                
                if task_id:
                    # 尝试从Task表获取详细信息
                    task = session.query(Task).filter_by(id=task_id).first()
                    if task:
                        task_progress = task.completion_percentage or 0
                
                return {
                    'id': text_prd.id,
                    'name': task_name,
                    'type': 'text',
                    'status': 'processing',
                    'progress': task_progress
                }
            
            # 3. 检查旧架构的Task表（兼容历史数据）
            # 运行中的状态：processing, running, analyzing, collaborating, 
            #              pm_responding, checking_intervention, waiting_confirmation,
            #              finalizing_prd, generating_testcases, writing_testcases
            running_statuses = [
                'processing', 'running', 'analyzing', 'collaborating',
                'pm_responding', 'checking_intervention', 'waiting_confirmation',
                'finalizing_prd', 'generating_testcases', 'writing_testcases'
            ]
            
            old_task = session.query(Task).filter(
                Task.status.in_(running_statuses)
            ).first()
            
            if old_task:
                return {
                    'id': old_task.id,
                    'name': old_task.name or '未命名任务',
                    'type': 'text',
                    'status': old_task.status,
                    'progress': old_task.completion_percentage or 0
                }
            
            # 没有运行中的任务
            return None
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"检查运行中任务失败: {e}", exc_info=True)
        # 出错时返回None，允许任务启动（避免因检查失败而阻塞正常流程）
        return None
