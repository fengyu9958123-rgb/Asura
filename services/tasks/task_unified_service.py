"""
统一任务服务 - 整合图片需求和文本PRD的查询和管理
根据 UI_REDESIGN_PLAN_A.md 设计文档实现
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional
from database.models import RequirementModule, PRD, Task, TaskStatus, DatabaseManager

logger = logging.getLogger(__name__)


class TaskUnifiedService:
    """统一任务服务 - 提供统一的任务查询和管理接口"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        logger.info("TaskUnifiedService initialized")
    
    def list_tasks(
        self,
        status_group: Optional[str] = None,  # draft/pending/processing/waiting/completed/failed
        task_type: Optional[str] = None,     # image/text/all
        status: Optional[str] = None,        # 具体状态
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict:
        """
        统一任务列表查询
        
        Returns:
            {
                'tasks': [...],  # TaskViewModel数组
                'total': 128,
                'group_counts': {
                    'draft': 3,
                    'pending': 2,
                    'processing': 3,
                    'waiting': 2,
                    'completed': 20,
                    'failed': 1
                }
            }
        """
        session = self.db_manager.get_session()
        
        try:
            all_tasks = []
            
            # 1. 查询图片需求任务
            if not task_type or task_type in ['all', 'image']:
                image_tasks = self._query_image_tasks(
                    session, status_group, status, start_date, end_date, keyword
                )
                all_tasks.extend(image_tasks)
            
            # 2. 查询文本PRD任务
            if not task_type or task_type in ['all', 'text']:
                text_tasks = self._query_text_tasks(
                    session, status_group, status, start_date, end_date, keyword
                )
                all_tasks.extend(text_tasks)
            
            # 3. 按更新时间排序
            all_tasks.sort(key=lambda x: x['updated_at'], reverse=True)
            
            # 4. 计算分组统计
            group_counts = self._calculate_group_counts(all_tasks)
            
            # 5. 分页
            total = len(all_tasks)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_tasks = all_tasks[start_idx:end_idx]
            
            logger.info(f"统一任务列表查询: 总数={total}, 图片={sum(1 for t in all_tasks if t['type']=='image')}, 文本={sum(1 for t in all_tasks if t['type']=='text')}")
            
            return {
                'tasks': paginated_tasks,
                'total': total,
                'group_counts': group_counts
            }
            
        finally:
            session.close()
    
    def _query_image_tasks(
        self, 
        session, 
        status_group: Optional[str],
        status: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        keyword: Optional[str]
    ) -> List[Dict]:
        """查询图片需求任务"""
        query = session.query(RequirementModule)
        
        # 状态分组筛选
        if status_group:
            req_mod_statuses = self._get_requirement_module_statuses_by_group(status_group)
            if req_mod_statuses:
                query = query.filter(RequirementModule.status.in_(req_mod_statuses))
        
        # 具体状态筛选
        if status:
            req_mod_statuses = self._get_requirement_module_statuses_by_status(status)
            if req_mod_statuses:
                query = query.filter(RequirementModule.status.in_(req_mod_statuses))
        
        # 时间筛选
        if start_date:
            query = query.filter(RequirementModule.created_at >= start_date)
        if end_date:
            query = query.filter(RequirementModule.created_at <= end_date)
        
        # 关键词搜索
        if keyword:
            query = query.filter(RequirementModule.name.like(f'%{keyword}%'))
        
        modules = query.all()
        
        # 转换为统一的TaskViewModel
        tasks = []
        for module in modules:
            task_vm = self._convert_requirement_module_to_task_vm(module, session)
            if status_group and task_vm.get('status_group') != status_group:
                continue
            if status and task_vm.get('status') != status:
                continue
            tasks.append(task_vm)
        
        return tasks
    
    def _query_text_tasks(
        self,
        session,
        status_group: Optional[str],
        status: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        keyword: Optional[str]
    ) -> List[Dict]:
        """查询文本PRD任务（同时查询新架构PRD表和旧架构Task表）"""
        tasks = []
        
        # 1. 查询新架构PRD表
        prd_query = session.query(PRD)
        
        # 状态分组筛选
        if status_group:
            prd_statuses = self._get_prd_statuses_by_group(status_group)
            if prd_statuses:
                prd_query = prd_query.filter(PRD.status.in_(prd_statuses))
        
        # 具体状态筛选
        if status:
            prd_statuses = self._get_prd_statuses_by_status(status)
            if prd_statuses:
                prd_query = prd_query.filter(PRD.status.in_(prd_statuses))
        
        # 时间筛选
        if start_date:
            prd_query = prd_query.filter(PRD.created_at >= start_date)
        if end_date:
            prd_query = prd_query.filter(PRD.created_at <= end_date)
        
        # 关键词搜索
        if keyword:
            prd_query = prd_query.filter(PRD.name.like(f'%{keyword}%'))
        
        prds = prd_query.all()
        
        # 转换PRD为TaskViewModel
        for prd in prds:
            task_vm = self._convert_prd_to_task_vm(prd, session)
            if status_group and task_vm.get('status_group') != status_group:
                continue
            if status and task_vm.get('status') != status:
                continue
            tasks.append(task_vm)
        
        # 2. 查询旧架构Task表（兼容历史数据）
        # 注意：旧Task表没有type字段，所有旧任务都是文本PRD任务
        # 排除已在PRD表中的Task，以及图片任务相关的Task（prd_id以req_mod_开头）
        from sqlalchemy import not_

        all_prd_ids = [prd.id for prd in prds]
        task_query = session.query(Task).filter(
            not_(Task.prd_id.in_(all_prd_ids)),  # 排除已在PRD表中的Task
            ~Task.prd_id.like('req_mod_%')       # 排除图片任务相关的Task
        )

        # 状态分组筛选
        if status_group:
            task_statuses = self._get_task_statuses_by_group(status_group)
            if task_statuses:
                task_query = task_query.filter(Task.status.in_(task_statuses))

        # 具体状态筛选
        if status:
            task_query = task_query.filter(Task.status == status)

        # 时间筛选
        if start_date:
            task_query = task_query.filter(Task.created_at >= start_date)
        if end_date:
            task_query = task_query.filter(Task.created_at <= end_date)

        # 关键词搜索
        if keyword:
            task_query = task_query.filter(Task.name.like(f'%{keyword}%'))

        legacy_tasks = task_query.all()
        
        # 转换Task为TaskViewModel
        for task in legacy_tasks:
            task_vm = self._convert_task_to_task_vm(task)
            if status_group and task_vm.get('status_group') != status_group:
                continue
            if status and task_vm.get('status') != status:
                continue
            tasks.append(task_vm)
        
        logger.info(f"查询文本任务: PRD表={len(prds)}条, Task表(历史)={len(legacy_tasks)}条")
        
        return tasks
    
    def _get_confirmation_status(self, module: Optional[RequirementModule] = None, task: Optional[Task] = None) -> Dict:
        """获取确认状态信息（优先从module读取，如果没有则从task读取）"""
        import json

        # 优先从 module.confirmation_questions 读取
        if module and module.confirmation_questions:
            try:
                questions = json.loads(module.confirmation_questions)
                if isinstance(questions, list) and len(questions) > 0:
                    return {
                        'has_confirmation': True,
                        'confirmation_count': len(questions)
                    }
            except (json.JSONDecodeError, TypeError):
                pass

        # 如果 module 没有，则从 task.confirmation_items 读取
        if task and task.confirmation_items:
            try:
                items = json.loads(task.confirmation_items) if isinstance(task.confirmation_items, str) else task.confirmation_items
                if isinstance(items, list) and len(items) > 0:
                    return {
                        'has_confirmation': True,
                        'confirmation_count': len(items)
                    }
            except (json.JSONDecodeError, TypeError):
                pass

        # 默认返回无确认
        return {
            'has_confirmation': False,
            'confirmation_count': 0
        }

    def _convert_requirement_module_to_task_vm(self, module: RequirementModule, session) -> Dict:
        """将RequirementModule转换为TaskViewModel"""
        # 获取关联的Task信息
        task = None
        if module.generated_task_id:
            task = session.query(Task).filter_by(id=module.generated_task_id).first()
        
        # 获取历史运行次数（目前图片需求还未实现多次运行，返回0）
        history_count = 0

        # 状态映射（传入module参数用于判断确认状态）
        status_info = self._map_requirement_module_status(module.status, task, module)
        
        return {
            # 基础信息
            'id': module.id,
            'name': module.name,
            'type': 'image',
            
            # 状态信息
            'status': status_info['status'],
            'status_display': status_info['status_display'],
            'status_group': status_info['status_group'],
            'can_edit': status_info['can_edit'],
            'can_start': status_info['can_start'],
            'can_delete': status_info['can_delete'],
            'can_cancel': status_info['can_cancel'],
            
            # 来源信息
            'source_type': 'requirement_module',
            'source_id': module.id,
            'task_id': module.generated_task_id,
            
            # 内容信息
            'content': {
                'image_count': module.image_count or 0,
                'images': module.images or [],
                'notes_requirement': module.notes_requirement,
                'notes_testing': module.notes_testing,
            },
            
            'business': None,

            # 进度信息
            'progress': module.progress if module.progress is not None else 0,
            'current_phase': task.current_phase if task else None,
            
            # 时间信息
            'created_at': module.created_at.isoformat() if module.created_at else None,
            'updated_at': module.updated_at.isoformat() if module.updated_at else None,
            'started_at': module.submitted_at.isoformat() if module.submitted_at else None,
            'completed_at': module.completed_at.isoformat() if module.completed_at else None,
            
            # 结果信息
            # 优先从 module.confirmation_questions 读取，如果没有则从 task.confirmation_items 读取
            'has_confirmation': self._get_confirmation_status(module, task)['has_confirmation'],
            'confirmation_count': self._get_confirmation_status(module, task)['confirmation_count'],
            'result_files': task.result_files if task else None,
            
            # 历史记录
            'history_count': history_count,
        }
    
    def _convert_prd_to_task_vm(self, prd: PRD, session) -> Dict:
        """将PRD转换为TaskViewModel"""
        # 获取关联的Task信息
        task = None
        if prd.generated_task_id:
            task = session.query(Task).filter_by(id=prd.generated_task_id).first()
        
        # 获取历史运行次数（查询该PRD的所有Task）
        history_count = session.query(Task).filter_by(prd_id=prd.id).count()
        
        # 状态映射
        status_info = self._map_prd_status(prd.status, task)
        
        return {
            # 基础信息
            'id': prd.id,
            'name': prd.name,
            'type': 'text',
            
            # 状态信息
            'status': status_info['status'],
            'status_display': status_info['status_display'],
            'status_group': status_info['status_group'],
            'can_edit': status_info['can_edit'],
            'can_start': status_info['can_start'],
            'can_delete': status_info['can_delete'],
            'can_cancel': status_info['can_cancel'],
            
            # 来源信息
            'source_type': 'prd',
            'source_id': prd.id,
            'task_id': prd.generated_task_id,
            
            # 内容信息
            'content': {
                'prd_content': prd.content,
            },
            
            'business': prd.business,
            
            # 进度信息
            'progress': task.completion_percentage if task else 0,
            'current_phase': task.current_phase if task else None,
            
            # 时间信息
            'created_at': prd.created_at.isoformat() if prd.created_at else None,
            'updated_at': prd.updated_at.isoformat() if prd.updated_at else None,
            'started_at': task.created_at.isoformat() if task else None,
            'completed_at': task.updated_at.isoformat() if (task and task.status == TaskStatus.COMPLETED) else None,
            
            # 结果信息
            'has_confirmation': bool(task and task.confirmation_items) if task else False,
            'confirmation_count': len(task.confirmation_items) if task and task.confirmation_items else 0,
            'result_files': task.result_files if task else None,
            
            # 历史记录
            'history_count': history_count,
        }
    
    def _map_requirement_module_status(self, module_status: str, task: Optional[Task] = None, module: Optional[RequirementModule] = None) -> Dict:
        """映射RequirementModule状态到统一状态"""
        task_status = task.status.value if task and task.status else None

        # draft - 草稿（可直接启动）
        if module_status == 'draft':
            return {
                'status': 'draft',
                'status_display': '📝 草稿',
                'status_group': 'draft',
                'can_edit': True,
                'can_start': True,  # 允许草稿直接启动
                'can_delete': True,
                'can_cancel': False
            }
        
        # submitted - 旧数据遗留状态，映射为草稿（新流程已废弃此状态）
        elif module_status == 'submitted':
            return {
                'status': 'draft',
                'status_display': '📝 草稿',
                'status_group': 'draft',
                'can_edit': True,
                'can_start': True,
                'can_delete': True,
                'can_cancel': False
            }
        
        # processing + waiting_confirmation - 等待确认
        # 判断条件：1) Task状态为waiting_confirmation 或 2) 有confirmation_questions但没有confirmation_answers
        has_confirmation_questions = module and module.confirmation_questions and module.confirmation_questions.strip() not in ['', '[]', 'null']
        has_confirmation_answers = module and module.confirmation_answers and module.confirmation_answers.strip() not in ['', '[]', 'null']
        is_waiting_confirmation = (
            (task_status == 'waiting_confirmation') or
            (has_confirmation_questions and not has_confirmation_answers)
        )

        if module_status == 'waiting_confirmation' or (module_status == 'processing' and is_waiting_confirmation):
            return {
                'status': 'waiting_confirmation',
                'status_display': '✋ 等待确认',
                'status_group': 'waiting',
                'can_edit': False,
                'can_start': False,
                'can_delete': False,
                'can_cancel': False
            }

        # processing + (running/analyzing/...) - 运行中
        elif module_status == 'processing':
            return {
                'status': 'processing',
                'status_display': '⚙️ 运行中',
                'status_group': 'processing',
                'can_edit': False,
                'can_start': False,
                'can_delete': False,
                'can_cancel': True
            }
        
        # completed - 已完成（可二次编辑）
        elif module_status == 'completed':
            return {
                'status': 'completed',
                'status_display': '✅ 已完成',
                'status_group': 'completed',
                'can_edit': True,  # 可二次编辑
                'can_start': True,  # 可重新启动
                'can_delete': True,
                'can_cancel': False
            }
        
        # failed - 失败
        elif module_status == 'failed':
            return {
                'status': 'failed',
                'status_display': '❌ 失败',
                'status_group': 'failed',
                'can_edit': True,
                'can_start': True,
                'can_delete': True,
                'can_cancel': False
            }
        
        # 默认
        else:
            return {
                'status': module_status,
                'status_display': module_status,
                'status_group': 'draft',
                'can_edit': True,
                'can_start': False,
                'can_delete': True,
                'can_cancel': False
            }
    
    def _map_prd_status(self, prd_status: str, task: Optional[Task] = None) -> Dict:
        """映射PRD状态到统一状态
        
        优先级：Task终态 > Task运行态 > PRD状态
        """
        task_status = task.status.value if task and task.status else None
        
        # ========== 优先检查Task终态状态（避免PRD状态未同步导致显示错误） ==========
        
        # Task: completed - 已完成（可二次编辑）
        if task and task_status == 'completed':
            return {
                'status': 'completed',
                'status_display': '✅ 已完成',
                'status_group': 'completed',
                'can_edit': True,  # 可二次编辑
                'can_start': True,  # 可重新启动
                'can_delete': True,
                'can_cancel': False
            }
        
        # Task: failed - 失败
        elif task and task_status == 'failed':
            return {
                'status': 'failed',
                'status_display': '❌ 失败',
                'status_group': 'failed',
                'can_edit': True,
                'can_start': True,
                'can_delete': True,
                'can_cancel': False
            }
        
        # Task: cancelled - 已取消
        elif task and task_status == 'cancelled':
            return {
                'status': 'cancelled',
                'status_display': '🚫 已取消',
                'status_group': 'failed',
                'can_edit': True,
                'can_start': True,
                'can_delete': True,
                'can_cancel': False
            }
        
        # ========== 检查Task运行态状态 ==========
        
        # Task: waiting_confirmation - 等待确认
        elif task and task_status == 'waiting_confirmation':
            return {
                'status': 'waiting_confirmation',
                'status_display': '✋ 等待确认',
                'status_group': 'waiting',
                'can_edit': False,
                'can_start': False,
                'can_delete': False,
                'can_cancel': False
            }
        
        # ========== 检查PRD状态 ==========
        
        # draft - 草稿（可直接启动，包括已创建Task但未启动的情况）
        elif prd_status == 'draft':
            return {
                'status': 'draft',
                'status_display': '📝 草稿',
                'status_group': 'draft',
                'can_edit': True,
                'can_start': True,  # 允许草稿直接启动
                'can_delete': True,
                'can_cancel': False
            }
        
        # processing - 运行中
        elif prd_status == 'processing':
            return {
                'status': 'processing',
                'status_display': '⚙️ 运行中',
                'status_group': 'processing',
                'can_edit': False,
                'can_start': False,
                'can_delete': False,
                'can_cancel': True
            }
        
        # completed - 已完成（可二次编辑）
        elif prd_status == 'completed':
            return {
                'status': 'completed',
                'status_display': '✅ 已完成',
                'status_group': 'completed',
                'can_edit': True,  # 可二次编辑
                'can_start': True,  # 可重新启动
                'can_delete': True,
                'can_cancel': False
            }
        
        # 默认
        else:
            return {
                'status': prd_status,
                'status_display': prd_status,
                'status_group': 'draft',
                'can_edit': True,
                'can_start': False,
                'can_delete': True,
                'can_cancel': False
            }
    
    def _get_requirement_module_statuses_by_group(self, group: str) -> List[str]:
        """根据状态分组获取RequirementModule的状态列表"""
        mapping = {
            'draft': ['draft', 'submitted'],  # submitted是旧数据，映射为draft
            'processing': ['processing'],
            'waiting': ['processing', 'waiting_confirmation'],  # processing 需要结合确认字段判断
            'completed': ['completed'],
            'failed': ['failed']
        }
        return mapping.get(group, [])

    def _get_requirement_module_statuses_by_status(self, status: str) -> List[str]:
        """根据统一状态获取RequirementModule的候选原始状态列表。"""
        mapping = {
            'draft': ['draft', 'submitted'],
            'processing': ['processing'],
            'waiting_confirmation': ['processing', 'waiting_confirmation'],
            'completed': ['completed'],
            'failed': ['failed'],
        }
        return mapping.get(status, [status])
    
    def _get_prd_statuses_by_group(self, group: str) -> List[str]:
        """根据状态分组获取PRD的状态列表"""
        mapping = {
            'draft': ['draft'],
            'processing': ['processing'],
            'waiting': ['processing'],  # processing + waiting_confirmation task
            'completed': ['completed'],
            'failed': []  # 通过Task状态判断
        }
        return mapping.get(group, [])

    def _get_prd_statuses_by_status(self, status: str) -> List[str]:
        """根据统一状态获取PRD的候选原始状态列表。"""
        mapping = {
            'draft': ['draft'],
            'processing': ['processing'],
            'waiting_confirmation': ['processing'],
            'completed': ['completed'],
            'failed': [],
        }
        return mapping.get(status, [status])
    
    def _calculate_group_counts(self, tasks: List[Dict]) -> Dict[str, int]:
        """计算各状态分组的数量"""
        counts = {
            'draft': 0,
            'processing': 0,
            'waiting': 0,
            'completed': 0,
            'failed': 0
        }
        
        for task in tasks:
            group = task.get('status_group', 'draft')
            if group in counts:
                counts[group] += 1
        
        return counts
    
    def get_dashboard_stats(self) -> Dict:
        """获取工作台统计数据"""
        session = self.db_manager.get_session()
        
        try:
            # 获取所有任务
            all_tasks_result = self.list_tasks(page=1, page_size=9999)
            all_tasks = all_tasks_result['tasks']
            
            # 统计
            total_tasks = len(all_tasks)
            processing_tasks = sum(1 for t in all_tasks if t['status_group'] in ['processing', 'waiting'])
            waiting_confirmation = sum(1 for t in all_tasks if t['status_group'] == 'waiting')
            
            # 今日完成任务数
            today = datetime.utcnow().date()
            completed_today = sum(
                1 for t in all_tasks 
                if t['status_group'] == 'completed' and t['completed_at'] and 
                datetime.fromisoformat(t['completed_at']).date() == today
            )
            
            # 最近任务（最多5个）
            recent_tasks = all_tasks[:5]
            
            return {
                'total_tasks': total_tasks,
                'processing_tasks': processing_tasks,
                'waiting_confirmation': waiting_confirmation,
                'completed_today': completed_today,
                'recent_tasks': recent_tasks
            }
            
        finally:
            session.close()
    
    def get_task_history(self, unified_task_id: str, task_type: str) -> Dict:
        """
        获取某个统一任务的所有历史运行记录
        
        Args:
            unified_task_id: 统一任务ID（PRD ID 或 RequirementModule ID）
            task_type: 任务类型（'text' 或 'image'）
        
        Returns:
            {
                'history': [
                    {
                        'task_id': 'task_xxx',
                        'status': 'completed',
                        'status_display': '✅ 已完成',
                        'created_at': '2025-10-27 10:00:00',
                        'updated_at': '2025-10-27 10:30:00',
                        'completion_percentage': 100,
                        'message': '生成成功'
                    },
                    ...
                ],
                'total': 3
            }
        """
        session = self.db_manager.get_session()
        
        try:
            # 根据任务类型查询对应的源数据
            if task_type == 'text':
                # 文本PRD：通过prd_id查询所有Task
                tasks = session.query(Task).filter_by(prd_id=unified_task_id)\
                    .order_by(Task.created_at.desc()).all()
            elif task_type == 'image':
                # 图片需求：目前还未实现启动，暂时返回空
                # TODO: 未来需要在RequirementModule中添加类似的关联
                logger.warning(f"Image task history not implemented yet for module {unified_task_id}")
                return {'history': [], 'total': 0}
            else:
                logger.error(f"Unknown task type: {task_type}")
                return {'history': [], 'total': 0}
            
            # 转换为历史记录格式
            history = []
            for task in tasks:
                history.append({
                    'task_id': task.id,
                    'status': task.status.value if task.status else 'created',
                    'status_display': self._get_task_status_display(task.status.value if task.status else 'created'),
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'updated_at': task.updated_at.isoformat() if task.updated_at else None,
                    'completion_percentage': task.completion_percentage or 0,
                    'message': task.message or ''
                })
            
            return {
                'history': history,
                'total': len(history)
            }
            
        except Exception as e:
            logger.error(f"Failed to get task history: {str(e)}")
            return {'history': [], 'total': 0}
        finally:
            session.close()
    
    def _get_task_status_display(self, status: str) -> str:
        """获取Task状态的显示文本"""
        status_map = {
            'created': '🎯 待启动',
            'running': '⚙️ 运行中',
            'analyzing': '🔍 分析中',
            'collaborating': '🤝 协作中',
            'processing': '⚙️ 运行中',
            'finalizing_prd': '📝 整理最终PRD',
            'waiting_confirmation': '✋ 等待确认',
            'completed': '✅ 已完成',
            'failed': '❌ 失败',
            'cancelled': '🚫 已取消'
        }
        return status_map.get(status, status)
    
    def _get_task_statuses_by_group(self, group: str) -> List[str]:
        """根据状态分组获取Task的状态列表（用于兼容旧数据）"""
        mapping = {
            'draft': ['created'],
            'processing': ['processing', 'running', 'analyzing', 'collaborating', 'pm_responding', 'checking_intervention', 'finalizing_prd'],
            'waiting': ['waiting_confirmation'],
            'completed': ['completed'],
            'failed': ['failed', 'error']
        }
        return mapping.get(group, [])
    
    def _convert_task_to_task_vm(self, task: Task) -> Dict:
        """将Task（旧架构）转换为TaskViewModel"""
        # 状态映射（处理枚举类型）
        if hasattr(task.status, 'value'):
            # 枚举类型，获取value
            status_lower = task.status.value.lower()
        elif isinstance(task.status, str):
            # 字符串类型，直接转小写
            status_lower = task.status.lower()
        else:
            # 其他类型，转字符串后转小写，并去除 "taskstatus." 前缀
            status_str = str(task.status).lower()
            status_lower = status_str.replace('taskstatus.', '')
        
        # 确定状态分组
        if status_lower in ['created']:
            status_group = 'draft'
        elif status_lower in ['processing', 'running', 'analyzing', 'collaborating', 'pm_responding', 'checking_intervention', 'finalizing_prd']:
            status_group = 'processing'
        elif status_lower in ['waiting_confirmation']:
            status_group = 'waiting'
        elif status_lower in ['completed']:
            status_group = 'completed'
        elif status_lower in ['failed', 'error', 'cancelled']:
            status_group = 'failed'
        else:
            status_group = 'draft'
        
        # 操作权限
        can_edit = status_lower in ['created', 'failed', 'error']
        can_start = status_lower in ['created']
        can_delete = status_lower in ['created', 'completed', 'failed', 'error', 'cancelled']
        can_cancel = status_lower in ['processing', 'running', 'analyzing', 'collaborating', 'waiting_confirmation']
        
        return {
            # 基础信息
            'id': task.id,
            'name': task.name or '未命名任务',
            'type': 'text',
            
            # 状态信息
            'status': status_lower,
            'status_display': self._get_task_status_display(status_lower),
            'status_group': status_group,
            'can_edit': can_edit,
            'can_start': can_start,
            'can_delete': can_delete,
            'can_cancel': can_cancel,
            
            # 来源信息
            'source_type': 'task',
            'source_id': task.id,
            'task_id': task.id,
            'prd_id': task.prd_id,
            
            # 内容信息
            'content': {
                'prd_preview': (task.prd_content[:200] + '...') if task.prd_content and len(task.prd_content) > 200 else task.prd_content,
            },
            
            'business': task.business,
            
            # 进度信息
            'progress': task.completion_percentage or 0,
            'current_phase': task.current_phase,
            
            # 时间信息
            'created_at': task.created_at.isoformat() if task.created_at else None,
            'updated_at': task.updated_at.isoformat() if task.updated_at else None,
            'started_at': None,  # 旧Task表没有started_at字段
            'completed_at': None,  # 旧Task表没有completed_at字段
            
            # 运行信息
            'history_count': 0,  # 旧Task不支持多次运行
            'run_count': 0,
        }
