"""
通知服务 - 负责处理通知和日志记录
纯HTTP方案: 移除WebSocket依赖，只记录日志
"""

import logging
import json
from datetime import datetime

class NotificationService:
    """
    通知服务 - 提供日志记录和事件通知功能
    在纯HTTP方案中，只负责记录日志，不发送WebSocket消息
    """
    
    def __init__(self, logger=None):
        """
        初始化通知服务
        
        Args:
            logger: 日志记录器或LoggingService实例
        """
        if logger is None:
            self.logger = logging.getLogger(__name__)
        elif hasattr(logger, 'logger'):
            # 如果传入的是LoggingService实例，获取其内部logger
            self.logger = logger.logger
        else:
            # 否则使用传入的logger
            self.logger = logger
            
        self.logger.info("通知服务初始化完成")
    
    def notify_task_created(self, task_id, task_name, created_at=None):
        """
        记录任务创建通知
        
        Args:
            task_id: 任务ID
            task_name: 任务名称
            created_at: 创建时间
        """
        if isinstance(created_at, str):
            created_time = created_at
        elif hasattr(created_at, 'isoformat'):
            created_time = created_at.isoformat()
        else:
            created_time = datetime.now().isoformat()
            
        self.logger.info(f"任务创建: {task_id}, 名称: {task_name}")
    
    def notify_task_started(self, task_id):
        """
        记录任务启动通知
        
        Args:
            task_id: 任务ID
        """
        self.logger.info(f"任务启动: {task_id}")
    
    def notify_task_status_update(self, task_id, status, completion_percentage=0, message=None):
        """
        记录任务状态更新通知
        
        Args:
            task_id: 任务ID
            status: 新状态
            completion_percentage: 完成百分比
            message: 状态消息
        """
        self.logger.info(f"任务状态更新: {task_id}, 状态: {status}, 进度: {completion_percentage}%, 消息: {message}")
    
    def notify_agent_message(self, task_id, agent, message):
        """
        记录智能体消息通知
        
        Args:
            task_id: 任务ID
            agent: 智能体名称
            message: 消息内容
        """
        message_preview = message[:100] + "..." if len(message) > 100 else message
        self.logger.info(f"智能体消息: {task_id}, 智能体: {agent}, 消息预览: {message_preview}")
    
    def notify_confirmation_needed(self, task_id, items):
        """
        记录需要确认通知
        
        Args:
            task_id: 任务ID
            items: 确认项列表
        """
        self.logger.info(f"需要确认: {task_id}, 确认项数量: {len(items)}")
    
    def notify_confirmation_received(self, task_id, confirmation_count):
        """
        记录确认收到通知
        
        Args:
            task_id: 任务ID
            confirmation_count: 确认项数量
        """
        self.logger.info(f"确认已收到: {task_id}, 确认项数量: {confirmation_count}")
    
    def notify_task_cancelled(self, task_id):
        """
        记录任务取消通知
        
        Args:
            task_id: 任务ID
        """
        self.logger.info(f"任务已取消: {task_id}")
    
    def notify_status_update(self, task_id, status, completion_percentage=0, message=None):
        """
        记录状态更新通知 (兼容性方法)
        
        Args:
            task_id: 任务ID
            status: 新状态
            completion_percentage: 完成百分比
            message: 状态消息
        """
        self.notify_task_status_update(task_id, status, completion_percentage, message)
    
    def notify_log_message(self, task_id, level, message):
        """
        记录日志消息
        
        Args:
            task_id: 任务ID
            level: 日志级别
            message: 日志消息
        """
        log_level = getattr(logging, level.upper() if isinstance(level, str) else "INFO")
        self.logger.log(log_level, f"任务日志: {task_id}, 消息: {message}")
    
    def notify_confirmation_submitted(self, task_id):
        """
        记录确认提交通知
        
        Args:
            task_id: 任务ID
        """
        self.logger.info(f"确认已提交: {task_id}")
    
    def notify_results_ready(self, task_id):
        """
        记录结果就绪通知
        
        Args:
            task_id: 任务ID
        """
        self.logger.info(f"结果就绪: {task_id}") 
    
    def notify_log(self, task_id, message, level="INFO"):
        """
        记录日志消息 (兼容旧代码的别名方法)
        
        Args:
            task_id: 任务ID
            message: 日志消息
            level: 日志级别
        """
        self.notify_log_message(task_id, level, message)
    
    def notify_error(self, task_id, error_message):
        """
        记录错误通知
        
        Args:
            task_id: 任务ID
            error_message: 错误消息
        """
        self.logger.error(f"任务错误: {task_id}, 错误: {error_message}") 