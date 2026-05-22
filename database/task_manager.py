"""
新的TaskManager实现 - 基于SQLite
兼容原有API，增加缓存和性能优化
"""

import uuid
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from database.models import (
    db_manager, Task, TaskLog, TaskMessage, PRD, TaskStatus
)


def safe_get_task_status(status_value):
    """安全地获取TaskStatus枚举值"""
    if isinstance(status_value, TaskStatus):
        return status_value
    
    if isinstance(status_value, str):
        # 通过值查找枚举
        for enum_item in TaskStatus:
            if enum_item.value == status_value:
                return enum_item
        # 如果找不到，返回默认状态
        return TaskStatus.CREATED
    
    # 其他类型转换为字符串后处理
    return safe_get_task_status(str(status_value))


class SQLiteTaskManager:
    """基于SQLite的任务管理器"""

    # 进程内共享缓存：避免 Flask 与后台 LangGraph 使用不同实例时读到过期任务数据
    _task_cache: Dict[str, Any] = {}
    _cache_timeout = 300  # 5分钟缓存超时
    
    def __init__(self, logger=None):
        """初始化任务管理器"""
        # 初始化数据库
        db_manager.initialize()
        
        # 设置日志记录器
        if logger is None:
            import logging
            self.logger = logging.getLogger(__name__)
        elif hasattr(logger, 'logger'):
            self.logger = logger.logger
        else:
            self.logger = logger
            
        self.logger.info("SQLite任务管理器初始化完成")
    
    def create_task(self, prd_id, prd_name, prd_content=None, mode=None, business=None):
        """创建新任务"""
        session = db_manager.get_session()
        
        try:
            # 处理prd_id
            prd_id_str = self._extract_prd_id(prd_id)
            
            # 生成任务ID
            task_id = f"{prd_id_str}_{uuid.uuid4()}"
            
            # 创建任务记录
            task = Task(
                id=task_id,
                prd_id=prd_id_str,
                name=prd_name,
                status=TaskStatus.CREATED,
                completion_percentage=0,
                message="任务已创建",
                prd_content=prd_content,
                mode=mode if mode else '普通模式',
                business=business
            )
            
            session.add(task)
            session.commit()
            
            # 清除缓存
            self._clear_cache(task_id)
            
            self.logger.info(f"创建任务: {task_id}, PRD名称: {prd_name}")
            return task_id  # 返回任务ID字符串，而不是完整的task字典
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"创建任务失败: {e}")
            raise
        finally:
            session.close()
    
    def get_task(self, task_id):
        """获取任务详情"""
        # 先检查缓存
        cached_task = self._get_from_cache(task_id)
        if cached_task:
            return cached_task
        
        session = db_manager.get_session()
        
        try:
            task = session.query(Task).filter_by(id=task_id).first()
            if not task:
                return None
            
            task_dict = self._task_to_dict(task)
            
            # 加载消息和日志
            task_dict['messages'] = self._get_task_messages_from_db(task_id, session)
            task_dict['logs'] = self._get_task_logs_from_db(task_id, session)
            
            # 缓存结果
            self._set_cache(task_id, task_dict)
            
            return task_dict
            
        except Exception as e:
            self.logger.error(f"获取任务失败: {e}")
            return None
        finally:
            session.close()
    
    def update_task(self, task_id, **updates):
        """更新任务属性"""
        session = db_manager.get_session()

        try:
            task = session.query(Task).filter_by(id=task_id).first()
            if not task:
                self.logger.error(f"更新任务失败: 任务 {task_id} 不存在")
                return None

            # 更新字段
            for key, value in updates.items():
                if hasattr(task, key):
                    setattr(task, key, value)

            # 更新时间戳
            task.updated_at = datetime.now()

            # 🔄 同步更新关联的PRD状态（在commit之前，保证原子性）
            if 'status' in updates:
                self._sync_prd_status(session, task_id, updates['status'])

            # 统一提交（Task和PRD在同一个事务中）
            session.commit()

            # 清除缓存
            self._clear_cache(task_id)

            return self._task_to_dict(task)

        except Exception as e:
            session.rollback()
            self.logger.error(f"更新任务失败: {e}")
            return None
        finally:
            session.close()
    
    def update_task_status(self, task_id, status, completion_percentage=None, message=None):
        """更新任务状态"""
        # 安全地获取状态枚举
        status_enum = safe_get_task_status(status)

        updates = {"status": status_enum}

        if completion_percentage is not None:
            updates["completion_percentage"] = completion_percentage

        if message:
            updates["message"] = message

        self.logger.info(f"任务状态更新: {task_id}, {status}, 进度: {completion_percentage}%, 消息: {message}")
        return self.update_task(task_id, **updates)

    def _sync_prd_status(self, session, task_id, task_status):
        """同步更新关联的PRD状态

        当Task状态变为终态（completed/failed/cancelled）时，
        自动同步更新PRD表的状态，避免状态不一致

        注意：此方法不会调用commit，由调用方统一提交事务，保证原子性

        Args:
            session: 数据库会话（必须是活跃的session）
            task_id: 任务ID
            task_status: Task的新状态（TaskStatus枚举）
        """
        try:
            from database.models import PRD

            # 将TaskStatus枚举转换为字符串
            status_str = task_status.value if hasattr(task_status, 'value') else str(task_status)

            # 只处理终态状态
            if status_str not in ['completed', 'failed', 'cancelled']:
                return

            # 查找关联的PRD
            prd = session.query(PRD).filter_by(generated_task_id=task_id).first()

            if not prd:
                # 没有关联的PRD，跳过（图片任务或旧架构任务）
                return

            # 映射Task状态到PRD状态
            prd_status_map = {
                'completed': 'completed',
                'failed': 'failed',
                'cancelled': 'draft'  # 取消后恢复为草稿，允许重新编辑
            }

            new_prd_status = prd_status_map.get(status_str)

            if new_prd_status and prd.status != new_prd_status:
                old_status = prd.status
                prd.status = new_prd_status
                prd.updated_at = datetime.now()

                # 如果是完成状态，记录完成时间
                if new_prd_status == 'completed' and hasattr(prd, 'completed_at'):
                    prd.completed_at = datetime.now()

                # 不在这里commit，由update_task统一提交，保证Task和PRD在同一事务中

                self.logger.info(
                    f"✅ 同步PRD状态: PRD={prd.id}, "
                    f"{old_status} -> {new_prd_status} (Task={task_id}, status={status_str})"
                )

        except Exception as e:
            self.logger.error(f"同步PRD状态失败: {e}", exc_info=True)
            # 抛出异常，让外层的rollback能够回滚整个事务
            raise

    def add_message(self, task_id, sender, content):
        """添加对话消息"""
        session = db_manager.get_session()
        
        try:
            # 检查任务是否存在
            task_exists = session.query(Task).filter_by(id=task_id).first()
            if not task_exists:
                self.logger.error(f"添加消息失败: 任务 {task_id} 不存在")
                return False
            
            # 创建消息记录
            message = TaskMessage(
                id=str(uuid.uuid4()),
                task_id=task_id,
                sender=sender,
                content=content
            )
            
            session.add(message)
            session.commit()
            
            # 清除缓存
            self._clear_cache(task_id)
            
            return True
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"添加消息失败: {e}")
            return False
        finally:
            session.close()
    
    def add_log(self, task_id, level, message, extra_data=None):
        """添加日志"""
        session = db_manager.get_session()
        
        try:
            # 检查任务是否存在
            task_exists = session.query(Task).filter_by(id=task_id).first()
            if not task_exists:
                self.logger.error(f"添加日志失败: 任务 {task_id} 不存在")
                return False
            
            # 创建增强的日志消息
            enhanced_message = message
            if extra_data:
                # 如果有额外数据，将其序列化到消息中
                if isinstance(extra_data, dict):
                    # 提取关键信息到消息主体
                    step = extra_data.get('step', '')
                    action = extra_data.get('action', '')
                    component = extra_data.get('component', '')
                    duration = extra_data.get('duration', '')
                    progress = extra_data.get('progress', '')
                    
                    # 构建更详细的消息
                    parts = [message]
                    if step or action:
                        parts.append(f"[{step}: {action}]" if step and action else f"[{step or action}]")
                    if component:
                        parts.append(f"组件: {component}")
                    if duration:
                        parts.append(f"耗时: {duration}")
                    if progress:
                        parts.append(f"进度: {progress}%")
                    
                    enhanced_message = " | ".join(parts)
            
            # 创建日志记录
            log_entry = TaskLog(
                id=str(uuid.uuid4()),
                task_id=task_id,
                level=level,
                message=enhanced_message
            )
            
            session.add(log_entry)
            session.commit()
            
            # 清除缓存
            self._clear_cache(task_id)
            
            return True
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"添加日志失败: {e}")
            return False
        finally:
            session.close()
    
    def list_tasks(self, limit=20, offset=0):
        """列出最近任务"""
        session = db_manager.get_session()
        
        try:
            tasks = (session.query(Task)
                    .order_by(Task.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                    .all())
            
            return [self._task_to_dict(task) for task in tasks]
            
        except Exception as e:
            self.logger.error(f"获取任务列表失败: {e}")
            return []
        finally:
            session.close()
    
    def get_task_messages(self, task_id, limit=100):
        """获取任务消息历史"""
        session = db_manager.get_session()
        
        try:
            return self._get_task_messages_from_db(task_id, session, limit)
        finally:
            session.close()
    
    def get_task_logs(self, task_id, limit=100):
        """获取任务日志"""
        session = db_manager.get_session()
        
        try:
            return self._get_task_logs_from_db(task_id, session, limit)
        finally:
            session.close()
    
    def get_brief_status(self, task_id):
        """获取任务轻量级状态"""
        session = db_manager.get_session()
        
        try:
            task = session.query(Task).filter_by(id=task_id).first()
            if not task:
                return None
            
            status_value = task.status.value if hasattr(task.status, "value") else str(task.status).lower().replace("taskstatus.", "")
            has_confirmation_results = bool(task.confirmation_results)
            has_pending_confirmation_items = bool(task.confirmation_items) and not has_confirmation_results
            return {
                "status": status_value,
                "completion_percentage": task.completion_percentage,
                "needs_confirmation": status_value == TaskStatus.WAITING_CONFIRMATION.value,
                "has_confirmation_items": has_pending_confirmation_items,
                "has_pending_confirmation_items": has_pending_confirmation_items,
                "has_submitted_confirmation": has_confirmation_results,
                "updated_at": task.updated_at.isoformat(),
                "message": task.message or ""
            }
            
        except Exception as e:
            self.logger.error(f"获取任务状态失败: {e}")
            return None
        finally:
            session.close()
    
    def set_confirmation_items(self, task_id, items):
        """设置确认项"""
        return self.update_task(
            task_id,
            confirmation_items=items,
            status=TaskStatus.WAITING_CONFIRMATION
        )
    
    def submit_confirmation(self, task_id, answers):
        """提交确认回答"""
        session = db_manager.get_session()
        
        try:
            task = session.query(Task).filter_by(id=task_id).first()
            if not task or not task.confirmation_items:
                self.logger.warning(f"任务 {task_id} 没有待确认 项")
                return False
            
            # 更新确认项答案
            confirmation_items = task.confirmation_items.copy() if task.confirmation_items else []
            
            # 备份原始确认项
            task.confirmation_items_backup = confirmation_items
            
            # 更新确认项答案
            for i, item in enumerate(confirmation_items):
                answer_key = f"answer_{i}"
                if answer_key in answers:
                    item["answer"] = answers[answer_key]
            
            # 保存确认结果
            task.confirmation_results = answers
            
            # 更新任务
            task.confirmation_items = confirmation_items
            task.status = TaskStatus.PROCESSING
            task.updated_at = datetime.now()
            
            # 记录额外日志
            self.add_log(
                task_id,
                'INFO',
                f"用户提交了 {len(answers)} 个确认回答",
                {
                    'confirmation_items': confirmation_items,
                    'confirmation_results': answers
                }
            )
            
            session.commit()
            
            # 清除缓存
            self._clear_cache(task_id)
            
            return True
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"提交确认失败: {e}")
            return False
        finally:
            session.close()
    
    def save_results(self, task_id, testcases, result_files=None):
        """保存测试用例结果"""
        updates = {
            "testcases": testcases,
            "status": TaskStatus.COMPLETED,
            "completion_percentage": 100
        }
        
        if result_files:
            updates["result_files"] = result_files
        
        return self.update_task(task_id, **updates)
    
    def get_confirmation_items(self, task_id):
        """获取任务确认项"""
        task = self.get_task(task_id)
        if not task:
            return []

        # 如果已有确认结果，优先返回已提交结果。确认提交后原始 confirmation_items
        # 会被保留用于最终PRD整合，不能再被前端当成待确认项展示。
        if task.get('confirmation_results'):
            try:
                # 尝试解析确认结果
                results = task['confirmation_results']
                if isinstance(results, str):
                    import json
                    results = json.loads(results)
                
                # 返回已确认的结果，格式化为前端期望的格式
                if isinstance(results, list) and results:
                    formatted_results = []
                    original_items = task.get('confirmation_items') or task.get('confirmation_items_backup') or []
                    for index, result in enumerate(results):
                        if not isinstance(result, dict):
                            formatted_results.append(result)
                            continue
                        question_info = original_items[index] if isinstance(original_items, list) and len(original_items) > index else {}
                        formatted_results.append({
                            **result,
                            'question': (
                                result.get('question')
                                or question_info.get('question')
                                or question_info.get('title')
                                or result.get('confirmation_id')
                                or f'问题 {index + 1}'
                            ),
                            'description': (
                                result.get('description')
                                or question_info.get('description')
                                or result.get('question_details')
                                or ''
                            ),
                            'reference_examples': result.get('reference_examples') or question_info.get('reference_examples') or [],
                            'confirm_points': result.get('confirm_points') or question_info.get('confirm_points') or [],
                            'answer': result.get('user_answer') or result.get('answer') or '',
                            'is_submitted': True,
                        })
                    return formatted_results
                elif isinstance(results, dict):
                    # 将字典格式的确认结果转换为列表格式
                    formatted_results = []
                    metadata_keys = {'confirmed', 'submitted_at', 'task_id', 'confirmation_id', 'status'}
                    for key, value in results.items():
                        if key.startswith('answer_'):
                            index = key.split('_')[1]
                            try:
                                index = int(index)
                                # 尝试从原始confirmation_items中获取问题信息
                                question_info = {}
                                original_items = task.get('confirmation_items_backup') or task.get('confirmation_items') or []
                                if isinstance(original_items, list) and len(original_items) > index:
                                    question_info = original_items[index]
                                
                                formatted_results.append({
                                    'id': index,
                                    'question': (
                                        question_info.get('question')
                                        or question_info.get('title')
                                        or f'问题 {index+1}'
                                    ),
                                    'description': question_info.get('description', ''),
                                    'confirm_points': question_info.get('confirm_points', []),
                                    'reference_examples': question_info.get('reference_examples', []),
                                    'answer': value,
                                    'user_answer': value,
                                    'confirmed': True,
                                    'is_submitted': True
                                })
                            except (ValueError, IndexError):
                                # 如果无法解析索引，使用通用格式
                                formatted_results.append({
                                    'question': f'问题 {key}',
                                    'answer': value,
                                    'user_answer': value,
                                    'confirmed': True,
                                    'is_submitted': True
                                })
                        elif not str(key).startswith('_') and str(key) not in metadata_keys:
                            formatted_results.append({
                                'question': f'问题 {key}',
                                'answer': value,
                                'user_answer': value,
                                'confirmed': True,
                                'is_submitted': True
                            })
                    
                    # 确保结果按照索引排序
                    formatted_results.sort(key=lambda x: (
                        0 if isinstance(x.get('id'), int) else 1,
                        x.get('id') if isinstance(x.get('id'), int) else str(x.get('question', ''))
                    ))
                    return formatted_results
            except Exception as e:
                self.logger.error(f"解析确认结果失败: {e}")

        # 没有确认结果时才返回待确认项目
        if (task.get('confirmation_items') and
                isinstance(task.get('confirmation_items'), list) and
                len(task.get('confirmation_items')) > 0):
            return task['confirmation_items']
        
        # 如果任务已完成但没有确认结果，尝试从任务日志中恢复
        if task.get('status') == 'completed':
            session = db_manager.get_session()
            try:
                # 查找确认相关的日志
                logs = (session.query(TaskLog)
                       .filter_by(task_id=task_id)
                       .filter(TaskLog.message.like('%确认%'))
                       .order_by(TaskLog.timestamp.desc())
                       .limit(10)
                       .all())
                
                if logs:
                    for log in logs:
                        if (log.extra_data and isinstance(log.extra_data, dict) and 
                                log.extra_data.get('confirmation_items')):
                            return log.extra_data['confirmation_items']
            except Exception as e:
                self.logger.error(f"从日志恢复确认项失败: {e}")
            finally:
                session.close()
        
        return []
    
    def get_task_results(self, task_id):
        """获取任务结果"""
        task = self.get_task(task_id)
        if task and task.get('testcases'):
            return task['testcases']
        return None
    
    def delete_task(self, task_id):
        """删除任务及其相关数据"""
        session = db_manager.get_session()
        
        try:
            # 查找任务
            task = session.query(Task).filter_by(id=task_id).first()
            if not task:
                self.logger.warning(f"删除任务失败: 任务 {task_id} 不存在")
                return False
            
            task_name = task.name
            prd_id = task.prd_id
            
            self.logger.info(f"开始删除任务: {task_id} ({task_name})")
            
            # 1. 删除任务消息
            messages_deleted = session.query(TaskMessage).filter(TaskMessage.task_id == task_id).delete()
            self.logger.info(f"删除了 {messages_deleted} 条消息")
            
            # 2. 删除任务日志
            logs_deleted = session.query(TaskLog).filter(TaskLog.task_id == task_id).delete()
            self.logger.info(f"删除了 {logs_deleted} 条日志")
            
            # 3. 删除任务本身
            session.delete(task)
            self.logger.info(f"删除了任务记录")
            
            # 4. 检查是否需要删除PRD（如果没有其他任务引用）
            other_tasks_with_same_prd = session.query(Task).filter(
                Task.prd_id == prd_id,
                Task.id != task_id
            ).count()
            
            if other_tasks_with_same_prd == 0:
                # 没有其他任务引用这个PRD，可以删除
                prd_record = session.query(PRD).filter(PRD.id == prd_id).first()
                if prd_record:
                    session.delete(prd_record)
                    self.logger.info(f"删除了PRD记录: {prd_id}")
            else:
                self.logger.info(f"保留PRD记录 {prd_id} (还有 {other_tasks_with_same_prd} 个任务在使用)")
            
            session.commit()
            
            # 清除缓存
            self._clear_cache(task_id)
            
            self.logger.info(f"成功删除任务: {task_id} ({task_name})")
            return True
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"删除任务失败: {e}")
            return False
        finally:
            session.close()
    
    def delete_tasks_by_name(self, task_name):
        """根据任务名称删除所有匹配的任务"""
        session = db_manager.get_session()
        
        try:
            # 查找所有匹配名称的任务
            tasks = session.query(Task).filter(Task.name == task_name).all()
            
            if not tasks:
                self.logger.warning(f"没有找到名称为'{task_name}'的任务")
                return 0
            
            self.logger.info(f"找到 {len(tasks)} 个名称为'{task_name}'的任务，准备删除")
            
            deleted_count = 0
            for task in tasks:
                task_id = task.id
                
                # 使用已有的delete_task方法删除单个任务
                # 先关闭当前session，让delete_task创建自己的session
                session.close()
                
                if self.delete_task(task_id):
                    deleted_count += 1
                
                # 重新获取session继续处理下一个任务
                session = db_manager.get_session()
                # 重新查询剩余的任务，因为可能已经被删除
                tasks = session.query(Task).filter(Task.name == task_name).all()
            
            self.logger.info(f"成功删除了 {deleted_count} 个名称为'{task_name}'的任务")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"批量删除任务失败: {e}")
            return 0
        finally:
            session.close()
    
    # 私有方法
    def _extract_prd_id(self, prd_id):
        """提取PRD ID"""
        if isinstance(prd_id, dict) and 'id' in prd_id:
            return prd_id['id']
        elif isinstance(prd_id, str):
            try:
                if prd_id.startswith('{'):
                    prd_dict = json.loads(prd_id)
                    return prd_dict.get('id', str(uuid.uuid4()))
                return prd_id
            except:
                return prd_id
        return str(prd_id)
    
    def _task_to_dict(self, task):
        """将Task对象转换为字典"""
        # 安全获取状态值
        status_value = task.status
        if hasattr(status_value, 'value'):
            status_value = status_value.value
        elif isinstance(status_value, str):
            status_value = status_value
        else:
            status_value = str(status_value)
            
        return {
            "id": task.id,
            "prd_id": task.prd_id,
            "name": task.name,
            "status": status_value,
            "completion_percentage": task.completion_percentage,
            "message": task.message,
            "prd_content": task.prd_content,
            "testcases": task.testcases,
            "enhanced_prd": task.enhanced_prd,
            "final_prd": task.final_prd,
            "architect_questions": task.architect_questions,
            "confirmation_items": task.confirmation_items,
            "confirmation_results": task.confirmation_results,
            "result_files": task.result_files,
            "test_analysis": getattr(task, 'test_analysis', None),  # 测试分析报告
            # DeepSeek对话历史字段
            "product_manager_messages": task.product_manager_messages,
            "test_architect_messages": task.test_architect_messages,
            "test_analyst_messages": getattr(task, 'test_analyst_messages', None),  # 新增
            "test_case_writer_messages": task.test_case_writer_messages,
            "current_phase": task.current_phase,
            "mode": getattr(task, 'mode', '普通模式'),  # 安全获取模式字段
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat()
        }
    
    def _get_task_messages_from_db(self, task_id, session, limit=100):
        """从数据库获取任务消息"""
        messages = (session.query(TaskMessage)
                   .filter_by(task_id=task_id)
                   .order_by(TaskMessage.timestamp.desc())
                   .limit(limit)
                   .all())
        
        return [{
            "sender": msg.sender,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat()
        } for msg in messages]
    
    def _get_task_logs_from_db(self, task_id, session, limit=100):
        """从数据库获取任务日志"""
        logs = (session.query(TaskLog)
               .filter_by(task_id=task_id)
               .order_by(TaskLog.timestamp.desc())
               .limit(limit)
               .all())
        
        return [{
            "level": log.level,
            "message": log.message,
            "timestamp": log.timestamp.isoformat()
        } for log in logs]
    
    def _get_from_cache(self, task_id):
        """从缓存获取任务"""
        cache = type(self)._task_cache
        if task_id in cache:
            cached_data, timestamp = cache[task_id]
            if (datetime.now() - timestamp).seconds < self._cache_timeout:
                return cached_data
            del cache[task_id]
        return None
    
    def _set_cache(self, task_id, task_data):
        """设置缓存"""
        cache = type(self)._task_cache
        cache[task_id] = (task_data, datetime.now())
        
        # 简单的缓存清理
        if len(cache) > 100:
            oldest_key = min(cache.keys(), key=lambda k: cache[k][1])
            del cache[oldest_key]
    
    def _clear_cache(self, task_id):
        """清除指定任务的缓存"""
        cache = type(self)._task_cache
        if task_id in cache:
            del cache[task_id]
