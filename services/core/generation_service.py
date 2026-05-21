"""
生成服务 - 简化版
负责管理和协调生成测试用例的流程
不使用复杂的AutoGen配置，基于预定义模板生成
"""

import os
import time
import json
import re
import logging
import threading
import traceback
from datetime import datetime
from services.notifications.unified_task_logger import UnifiedTaskLogger
from services.generation.llm_response_cleaner import strip_model_reasoning
from services.generation.prd_document_cleaner import clean_prd_document

logger = logging.getLogger(__name__)

class SimplifiedGenerationService:
    """简化的生成服务，负责管理和协调生成测试用例的流程"""
    
    def __init__(self, agent_service, logging_service, file_service, socketio):
        """
        初始化生成服务
        
        Args:
            agent_service: 代理服务实例
            logging_service: 日志服务实例
            file_service: 文件服务实例
            socketio: 兼容旧接口的通知对象
        """
        from services.analysis.analysis_service import AnalysisService
        from services.generation.test_generation_service import TestGenerationService
        from services.notifications.notification_service import NotificationService
        from database.task_manager import SQLiteTaskManager
        
        self.agent_service = agent_service
        self.logging_service = logging_service
        self.file_service = file_service
        self.socketio = socketio
        
        # 子服务初始化
        self.task_manager = SQLiteTaskManager(logger=logging_service)
        self.notification_service = NotificationService(logger=logging_service)
            
        # 分析和生成服务
        self.analysis_service = AnalysisService(
            agent_service=agent_service,
            logging_service=logging_service,
            task_manager=self.task_manager
        )
        
        self.test_generation = TestGenerationService(
            agent_service=agent_service,
            logging_service=logging_service,
            file_service=file_service,
            task_manager=self.task_manager
        )
    
    def create_task(self, prd_id, prd_name, prd_content, mode=None, business=None):
        """创建任务"""
        try:
            # 创建任务记录
            task_id = self.task_manager.create_task(prd_id, prd_name, prd_content, mode, business)
            
            # 记录日志
            mode_info = f", 模式: {mode}" if mode else ""
            business_info = f", 业务: {business}" if business else ""
            logger.info(f"创建任务: {task_id}{mode_info}{business_info}")
            self.logging_service.log_system_event("创建任务", f"创建任务: {task_id}{mode_info}{business_info}")
            
            return task_id
        except Exception as e:
            logger.error(f"创建任务失败: {str(e)}")
            return None
    
    def get_task(self, task_id):
        """获取任务"""
        return self.task_manager.get_task(task_id)
    
    def list_tasks(self, limit=50):
        """列出任务"""
        return self.task_manager.list_tasks(limit=limit)
    
    def delete_task(self, task_id):
        """删除任务"""
        logger.info(f"删除任务: {task_id}")
        return self.task_manager.delete_task(task_id)
    
    def get_task_status(self, task_id):
        """获取任务状态"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"获取任务状态失败: 任务 {task_id} 不存在")
                return None
            
            # 提取需要的状态信息
            status_info = {
                'id': task_id,
                'status': task.get('status', 'unknown'),
                'message': task.get('message', ''),
                'completion_percentage': task.get('completion_percentage', 0),
                'created_at': task.get('created_at', ''),
                'updated_at': task.get('updated_at', '')
            }
            
            return status_info
        except Exception as e:
            logger.error(f"获取任务状态异常: {str(e)}")
            return None
    
    def cancel_task(self, task_id):
        """取消任务"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"取消任务失败: 任务 {task_id} 不存在")
                return False
            
            # 检查任务状态是否可取消
            current_status = task.get('status')
            if current_status in ['completed', 'cancelled', 'failed']:
                logger.warning(f"任务已经处于最终状态，无法取消: {current_status}")
                return False
            
            # 更新任务状态
            self.task_manager.update_task_status(
                task_id, 
                'cancelled', 
                task.get('completion_percentage', 0),
                '任务已取消'
            )
            
            # 记录日志
            self.task_manager.add_log(
                task_id,
                'WARNING',
                '任务已取消'
            )
            
            # 发送通知
            self.notification_service.notify_task_cancelled(task_id)
        
            return True
            
        except Exception as e:
            logger.error(f"取消任务异常: {e}")
            return False
    
    def start_task(self, task_id, mode="普通模式"):
        """启动任务
        
        用于从API接口手动启动任务处理流程
        
        Args:
            task_id: 任务ID
            mode: 智能体模式，可选值："普通模式"、"扩展模式"
            
        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            logger.info(f"手动启动任务: {task_id}，模式: {mode}")
            
            # 检查任务是否存在
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"启动任务失败: 任务 {task_id} 不存在")
                return False
                
            # 检查任务状态是否允许启动
            current_status = task.get('status')
            if current_status not in ['created', 'waiting']:
                logger.error(
                    f"启动任务失败: 任务 {task_id} 当前状态为 {current_status}，无法启动"
                )
                return False
                
            # 更新任务状态，并保存模式信息
            self.task_manager.update_task_status(
                task_id, 
                'processing', 
                10, 
                f'任务正在处理中 (模式: {mode})'
            )
            
            # 保存模式信息到任务数据  
            logger.info(f"准备更新任务 {task_id} 的模式为: {mode}")
            updated_task = self.task_manager.update_task(task_id, mode=mode)
            if not updated_task:
                logger.error(f"保存模式信息到任务 {task_id} 失败")
                return False
            
            logger.info(f"任务 {task_id} 模式更新成功: {updated_task.get('mode', '未找到mode字段')}")
            
            # 验证更新是否生效
            verify_task = self.task_manager.get_task(task_id)
            if verify_task:
                logger.info(f"验证: 任务 {task_id} 当前模式为: {verify_task.get('mode', '未找到mode字段')}")
            else:
                logger.error(f"验证失败: 无法重新获取任务 {task_id}")
            
            # 添加日志记录
            self.task_manager.add_log(
                task_id,
                'INFO',
                f"任务 {task_id} 启动成功，使用模式: {mode}"
            )
            
            # 发送通知
            self.notification_service.notify_task_started(task_id)
            
            # 在新线程中启动任务，传递模式参数
            threading.Thread(
                target=self.start_generation,
                args=(task_id, mode),
                daemon=True
            ).start()
            
            return True
            
        except Exception as e:
            logger.error(f"启动任务异常: {e}", exc_info=True)
            return False
    
    def get_pending_confirmations(self, task_id):
        """获取任务的待确认项"""
        task = self.task_manager.get_task(task_id)
        if not task or 'pending_confirmations' not in task:
            return []
        
        return task.get('pending_confirmations', [])
    
    def handle_confirmation(self, confirmation_id, confirmed, answers=None, task_id=None):
        """处理确认请求，用于前端确认对话框
        
        Args:
            confirmation_id: 确认ID
            confirmed: 是否确认
            answers: 回答内容列表
            task_id: 任务ID (可选)
            
        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            logger.info(f"处理确认请求: confirmation_id={confirmation_id}, confirmed={confirmed}")
            
            # 如果有task_id参数，从task_id中查找confirmation
            if task_id:
                task = self.task_manager.get_task(task_id)
                if not task:
                    logger.error(f"处理确认失败: 任务 {task_id} 不存在")
                    return False
                
                # 获取确认项并处理
                if confirmed:
                    logger.info(f"确认已接受: {confirmation_id}")
                    # 如果有回答，存储回答
                    if answers:
                        # 获取原始确认项信息
                        confirmation_items = task.get('confirmation_items', [])
                        original_item = None
                        
                        # 查找对应的原始确认项
                        for item in confirmation_items:
                            if item.get('id') == confirmation_id:
                                original_item = item
                                break
                        
                        confirmation_results = task.get('confirmation_results', [])
                        result_item = {
                            'confirmation_id': confirmation_id,
                            'answers': answers,
                            'confirmed': True,
                            'submitted_at': datetime.now().isoformat()
                        }
                        
                        # 如果找到原始确认项，包含问题详细信息
                        if original_item:
                            result_item.update({
                                'question': original_item.get('question', ''),
                                'description': original_item.get('description', ''),
                                'confirm_points': original_item.get('confirm_points', [])
                            })
                        else:
                            # 如果没有找到原始确认项，尝试从confirmation_id中获取信息
                            logger.warning(f"未找到confirmation_id为{confirmation_id}的原始确认项")
                            result_item.update({
                                'question': f'确认项{confirmation_id}',
                                'description': '',
                                'confirm_points': []
                            })
                        
                        confirmation_results.append(result_item)
                        task['confirmation_results'] = confirmation_results
                        
                        # 更新任务
                        self.task_manager.update_task(task_id, **{
                            'confirmation_results': confirmation_results
                        })
                        
                        # 处理确认结果
                        self.process_human_confirmation(task_id, confirmation_results)
                        
                    return True
                else:
                    logger.info(f"确认已拒绝: {confirmation_id}")
                    # 暂不处理拒绝的情况
                    return True
            
            # 使用confirmation_id查找任务
            else:
                # 从confirmation_id中提取task_id
                parts = confirmation_id.split(':')
                if len(parts) >= 2:
                    task_id = parts[0]
                    return self.handle_confirmation(
                        confirmation_id, 
                        confirmed, 
                        answers, 
                        task_id
                    )
                else:
                    logger.error(f"无效的confirmation_id格式: {confirmation_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"处理确认异常: {e}")
            return False
    
    def handle_task_confirmation(self, task_id, answers):
        """处理任务确认，用于批量提交确认回答
        
        Args:
            task_id: 任务ID
            answers: 包含确认回答的字典
            
        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"处理任务确认失败: 任务 {task_id} 不存在")
                return False
            
            # 获取确认项
            confirmations = task.get('confirmation_items', [])
            if not confirmations:
                logger.warning(f"任务 {task_id} 没有待确认项")
                return True
            
            # 构造确认结果
            confirmation_results = []
            for i, item in enumerate(confirmations):
                # 根据索引和ID两种方式获取回答
                answer_key = f'answer_{i}'
                item_id = item.get('id')
                
                # 尝试多种键值获取答案
                answer = answers.get(answer_key, '') or answers.get(item_id, '') or answers.get(f'answer_{item_id}', '')
                
                confirmation_results.append({
                    'confirmation_id': item_id or str(i),
                    'user_answer': answer,
                    'confirmed': True,
                    'submitted_at': datetime.now().isoformat(),
                    'question_details': item.get('question_details', f'确认项{i+1}')
                })
            
            # 更新任务
            task['confirmation_results'] = confirmation_results
            task['confirmation_items'] = []  # 清空待确认项
            
            confirmation_results_json = json.dumps(confirmation_results, ensure_ascii=False)
            logger.info(f"准备保存confirmation_results: 类型={type(confirmation_results)}, 长度={len(confirmation_results)}")
            logger.info(f"保存的JSON内容: {confirmation_results_json[:200]}...")
            
            self.task_manager.update_task(task_id, **{
                'confirmation_results': confirmation_results_json,
                'confirmation_items': []
            })
            
            # 验证保存是否成功
            updated_task = self.task_manager.get_task(task_id)
            saved_results = updated_task.get('confirmation_results', 'NOT_FOUND')
            logger.info(f"保存后验证: 数据库中的confirmation_results = {saved_results[:200] if isinstance(saved_results, str) else saved_results}")
            
            # 处理确认结果
            return self.process_human_confirmation(task_id, confirmation_results)
            
        except Exception as e:
            logger.error(f"处理任务确认异常: {e}")
            return False
    
    def submit_confirmation(self, task_id, confirmation_id, answers):
        """提交单个确认回答
        
        Args:
            task_id: 任务ID
            confirmation_id: 确认ID
            answers: 回答内容
            
        Returns:
            bool: 成功返回True，失败返回False
        """
        task = self.task_manager.get_task(task_id)
        if not task:
            logger.error(f"提交确认失败: 任务 {task_id} 不存在")
            return False
        
        # 获取待确认列表
        confirmations = task.get('pending_confirmations', [])
        
        # 查找特定确认项
        confirmation = None
        for item in confirmations:
            if item.get('id') == confirmation_id:
                confirmation = item
                break
        
        if not confirmation:
            return False
        
        # 移除待确认项
        confirmations.remove(confirmation)
        task['pending_confirmations'] = confirmations
        
        # 存储确认结果
        confirmation_results = task.get('confirmation_results', [])
        confirmation_results.append({
            'confirmation_id': confirmation_id,
            'answers': answers,
            'submitted_at': datetime.now().isoformat()
        })
        task['confirmation_results'] = confirmation_results
        
        # 更新任务
        self.task_manager.update_task(task_id, task)
        
        # 如果没有待确认项，继续处理
        if not confirmations:
            self.notification_service.notify_status_update(
                task_id, 
                'processing', 
                task.get('completion_percentage', 0),
                '人工确认完成，继续处理'
            )
        
        return True
    
    def start_generation(self, task_id, mode="普通模式"):
        """开始生成测试用例"""
        # 使用TaskManager的API检查任务是否存在
        task = self.task_manager.get_task(task_id)
        if not task:
            logger.error(f"任务不存在: {task_id}")
            return False
        
        # 检查任务状态 - 支持 created, running, processing 状态启动
        allowed_statuses = ['created', 'running', 'processing']
        current_status = task.get('status')
        if current_status not in allowed_statuses:
            logger.warning(f"任务状态不适合启动: {current_status}，允许的状态: {allowed_statuses}")
            return False
            
            # 更新任务状态
        self.task_manager.update_task_status(
            task_id, 
            'running', 
            10, 
            '开始生成测试用例'
        )
        
        # 创建线程运行生成流程
        thread = threading.Thread(
            target=self._run_generation_process,
            args=(task_id, mode)
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"开始任务: {task_id}")
        self.logging_service.log_system_event("任务启动", f"开始任务: {task_id}")
        return True

    def _run_generation_process(self, task_id, mode="普通模式"):
        """运行生成测试用例的完整流程 - 基于用户控制的阶段模式
        
        该方法实现用户控制的分阶段执行模式：
        - 自动执行：阶段1(PRD优化) → 阶段2(提问) → 阶段3(回答)
        - 如果有人工确认项：停下等待用户处理
        - 如果无人工确认项：继续自动执行阶段5(最终PRD) → 阶段6(测试用例)
        """
        start_time = time.time()
        
        # 使用TaskManager的API获取任务
        task = self.task_manager.get_task(task_id) 
        if not task:
            logger.error(f"任务不存在: {task_id}")
            return
        
        # 初始化统一日志器
        task_logger = UnifiedTaskLogger(task_id, 'text_prd')
        task_logger.log_task_start({
            'task_id': task_id,
            'mode': mode,
            'prd_name': task.get('prd_name', ''),
            'prd_id': task.get('prd_id', '')
        })
        
        # 记录流程开始
        task_logger.main_logger.info('🚀 任务处理流程开始 - 用户控制分阶段模式')
        self.task_manager.add_log(
            task_id, 'INFO', 
            '🚀 任务处理流程开始 - 用户控制分阶段模式',
            {
                'step': '开始',
                'action': '初始化流程',
                'component': 'GenerationService',
                'progress': 0,
                'mode': 'user_controlled_phases'
            }
        )
        
        try:
            # 检查必要的服务是否存在
            if not self.analysis_service or not self.test_generation:
                raise Exception("必要的分析或生成服务未正确初始化")
            
            # 首先清空AI智能体历史，确保没有历史数据污染
            logger.info(f"为任务 {task_id} 清空AI历史并重新初始化智能体实例...（模式: {mode}）")
            
            # 清空AI智能体历史
            logger.info("正在清空AI智能体历史...")
            if not self.agent_service.clear_agent_history(task_id):
                logger.warning("清空AI智能体历史失败，将强制重新初始化")
            
            # 初始化或重新初始化智能体实例
            if not self.agent_service.initialize_agents(task_id, mode):
                raise Exception("智能体初始化失败")
            
            self.task_manager.add_log(
                task_id, 'INFO',
                '✅ 智能体实例初始化完成',
                {
                    'step': '初始化',
                    'action': '智能体实例初始化',
                    'component': 'GenerationService',
                    'details': '所有智能体实例已准备就绪'
                }
            )
                
            # 初始化各Agent的对话历史（基于DeepSeek模式）
            self._initialize_agent_conversations(task_id)
                
            # 阶段1：ProductManager优化PRD（自动执行）
            self.notification_service.notify_log(task_id, "\n" + "="*70)
            self.notification_service.notify_log(task_id, "🔍 阶段1：ProductManager优化PRD")
            self.notification_service.notify_log(task_id, "="*70)
            
            result1 = self._execute_product_enhancement_with_ai(task_id)
            if not result1['success']:
                raise Exception(f"阶段1失败: {result1['error']}")
            
            # 阶段1确认项：清空并保存到confirmation_items字段，标记来源为阶段1
            stage1_confirmation_items = result1.get('confirmation_items', [])
            if stage1_confirmation_items and len(stage1_confirmation_items) > 0:
                logger.info(f"阶段1产生了 {len(stage1_confirmation_items)} 个确认项，保存待阶段3统一处理")
                # 为阶段1确认项添加来源标记
                for item in stage1_confirmation_items:
                    item['source_stage'] = 'stage1'
                # 直接保存到confirmation_items字段
                self.task_manager.update_task(task_id, **{
                    'confirmation_items': stage1_confirmation_items
                })
            else:
                logger.info("阶段1没有产生确认项，清空confirmation_items字段")
                # 清空confirmation_items字段，确保没有残留数据
                self.task_manager.update_task(task_id, **{
                    'confirmation_items': []
                })
                
            # 阶段2：TestArchitect提问（自动执行）
            self.notification_service.notify_log(task_id, "\n" + "="*70)
            self.notification_service.notify_log(task_id, "🤝 阶段2：TestArchitect提出问题")
            self.notification_service.notify_log(task_id, "="*70)
            
            result2 = self._execute_test_architect_qa_with_ai(task_id)
            if not result2['success']:
                raise Exception(f"阶段2失败: {result2['error']}")
            
            # 阶段3：ProductManager回答问题（自动执行）
            self.notification_service.notify_log(task_id, "\n" + "="*70)
            self.notification_service.notify_log(task_id, "📝 阶段3：ProductManager回答问题")
            self.notification_service.notify_log(task_id, "="*70)
            
            result3 = self._execute_product_manager_answer_with_ai(task_id)
            if not result3['success']:
                raise Exception(f"阶段3失败: {result3['error']}")
            
            # 统一收集所有阶段的确认项（阶段1和阶段3）
            stage3_confirmation_items = result3.get('confirmation_items', [])
            logger.info(f"阶段3中提取到 {len(stage3_confirmation_items)} 个新确认项")
            
            # 获取阶段1保存的确认项（从confirmation_items字段中读取）
            task = self.task_manager.get_task(task_id)
            existing_confirmation_items = task.get('confirmation_items', []) if task else []
            stage1_confirmation_items = [item for item in existing_confirmation_items if item.get('source_stage') == 'stage1']
            logger.info(f"阶段1确认项数量: {len(stage1_confirmation_items)}")
            
            # 为阶段3确认项添加来源标记
            for item in stage3_confirmation_items:
                item['source_stage'] = 'stage3'
            
            # 合并所有确认项并去重
            all_confirmation_items = self._deduplicate_confirmation_items(
                stage1_confirmation_items + stage3_confirmation_items
            )
            logger.info(f"合并去重后确认项总数: {len(all_confirmation_items)}")
            
            # 更新确认项ID，确保唯一性
            for i, item in enumerate(all_confirmation_items):
                if 'id' not in item or not item['id']:
                    item['id'] = f'human_confirm_{i+1}'
            
            if all_confirmation_items and len(all_confirmation_items) > 0:
                # 保存所有合并去重后的确认项到任务中
                self.task_manager.update_task(task_id, **{
                    'confirmation_items': all_confirmation_items
                })
                logger.info(f"所有确认项已保存: {[item.get('id') for item in all_confirmation_items]}")
                
                # 有人工确认项，停下等待用户处理
                logger.info(f"任务 {task_id} 需要人工确认，等待用户输入")
                self.task_manager.update_task_status(
                    task_id, 
                    'waiting_confirmation', 
                    50, 
                    f"✋ 等待人工确认({len(all_confirmation_items)}个问题)")
                
                # 记录详细的确认项信息
                self.task_manager.add_log(
                    task_id, 'INFO',
                    f"🤔 需要人工确认：发现{len(all_confirmation_items)}个问题",
                    {
                        'step': '人工确认',
                        'action': '等待确认',
                        'component': 'GenerationService',
                        'progress': 50,
                        'details': f'发现 {len(all_confirmation_items)} 个需要人工确认的问题'
                    }
                )
                
                self.notification_service.notify_log(task_id, "\n" + "="*70)
                self.notification_service.notify_log(task_id, f"🤔 发现{len(all_confirmation_items)}个需要人工确认的问题")
                self.notification_service.notify_log(task_id, "请在前端页面处理确认后继续")
                self.notification_service.notify_log(task_id, "="*70)
                
                # 停下等待用户处理确认，不继续执行
                return
            else:
                # 没有人工确认项，继续自动执行后续阶段
                logger.info(f"任务 {task_id} 无需人工确认，继续自动执行后续流程")
                self.task_manager.add_log(
                    task_id, 'INFO',
                    "✅ 无需人工确认，继续自动执行后续阶段"
                )
                
                # 继续执行后续阶段
                self._continue_automatic_execution(task_id, task_logger)
            
        except Exception as e:
            task_logger.log_error('GenerationProcess', str(e), e)
            task_logger.log_task_end('failed', str(e))
            
            logger.error(f"生成过程异常: {str(e)}")
            self.task_manager.update_task_status(
                task_id, 
                'failed', 
                0, 
                f"生成失败: {str(e)}")
            self.task_manager.add_log(task_id, "ERROR", f"生成过程异常: {str(e)}")
            self.notification_service.notify_error(task_id, f"生成失败: {str(e)}")
            
            # 记录完整堆栈信息到日志文件
            logger.error(f"任务 {task_id} 执行异常: {traceback.format_exc()}")
    
    def _continue_automatic_execution(self, task_id, task_logger=None):
        """继续自动执行剩余阶段（阶段5: 整合人工确认并生成最终PRD → 阶段6: 测试用例）"""
        # 创建或复用统一日志器
        if not task_logger:
            task_logger = UnifiedTaskLogger(task_id, 'text_prd')
        
        try:
            # 阶段5：ProductManager整合人工确认结果并生成最终PRD（合并原阶段4.5和5）
            self.notification_service.notify_log(task_id, "\n" + "="*70)
            self.notification_service.notify_log(task_id, "📋 阶段5：ProductManager整合人工确认并生成最终PRD")
            self.notification_service.notify_log(task_id, "="*70)
            
            result5 = self._execute_final_prd_generation_with_confirmation(task_id)
            if not result5['success']:
                raise Exception(f"阶段5失败: {result5['error']}")

            self.task_manager.update_task_status(
                task_id,
                'processing',
                75,
                "最终PRD已生成，准备生成测试用例"
            )
            
            self.notification_service.notify_log(task_id, "\n" + "="*70)
            self.notification_service.notify_log(task_id, "🔍 阶段5.5：PRD Knowledge 测试用例生成准备")
            self.notification_service.notify_log(task_id, "="*70)
            self.notification_service.notify_log(task_id, "💡 将在阶段6基于最终PRD分块、LU组装并生成测试用例")
            
            # 阶段6：ModuleTestCaseWriter生成测试用例（自动执行）
            self.notification_service.notify_log(task_id, "\n" + "="*70)
            self.notification_service.notify_log(task_id, "📝 阶段6：ModuleTestCaseWriter生成测试用例")
            self.notification_service.notify_log(task_id, "="*70)
            
            # 检查是否有测试分析指导
            self.task_manager.update_task_status(
                task_id,
                'processing',
                80,
                "正在生成测试用例"
            )
            self.notification_service.notify_log(task_id, "📖 正在基于最终PRD生成测试用例")
            
            result6 = self._execute_test_case_generation_with_ai(task_id)
            if not result6['success']:
                raise Exception(f"阶段6失败: {result6['error']}")
            
            # 任务完成
            self.notification_service.notify_log(task_id, "\n" + "="*70)
            self.notification_service.notify_log(task_id, "✅ 所有阶段自动执行完成！")
            self.notification_service.notify_log(task_id, "="*70)
            
            # 记录任务成功完成
            task_logger.log_task_end('success')
            logger.info(f"任务 {task_id} 自动执行完成")
            
        except Exception as e:
            task_logger.log_error('ContinueExecution', str(e), e)
            task_logger.log_task_end('failed', str(e))
            
            logger.error(f"自动执行剩余阶段异常: {str(e)}")
            self.task_manager.update_task_status(
                task_id, 
                'failed', 
                0, 
                f"自动执行失败: {str(e)}")
            self.task_manager.add_log(task_id, "ERROR", f"自动执行剩余阶段异常: {str(e)}")
            self.notification_service.notify_error(task_id, f"自动执行失败: {str(e)}")
    
    def _send_confirmation_to_product_manager(self, task_id):
        """将人工确认结果发送给ProductManager"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                return {'success': False, 'error': '任务不存在'}
            
            # 获取确认结果
            confirmation_results_str = task.get('confirmation_results', '[]')
            logger.info(f"获取到的confirmation_results_str: {type(confirmation_results_str)}, 内容: {str(confirmation_results_str)[:200]}")
            
            try:
                if isinstance(confirmation_results_str, str):
                    confirmation_results = json.loads(confirmation_results_str)
                else:
                    confirmation_results = confirmation_results_str or []
                
                logger.info(f"解析后的confirmation_results: {type(confirmation_results)}, 长度: {len(confirmation_results) if isinstance(confirmation_results, list) else 'N/A'}")
                
                if not confirmation_results:
                    # 添加更详细的调试信息
                    logger.error(f"没有找到确认结果 - task字段: {list(task.keys())}")
                    return {'success': False, 'error': '没有找到确认结果'}
                    
            except json.JSONDecodeError as e:
                logger.error(f"解析confirmation_results失败: {e}, 原始数据: {confirmation_results_str}")
                return {'success': False, 'error': f'解析确认结果失败: {str(e)}'}
            
            # 获取ProductManager智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents or 'product_manager' not in agents:
                return {'success': False, 'error': 'ProductManager智能体未初始化'}
            
            product_manager = agents['product_manager']
            
            # 获取ProductManager的对话历史
            product_manager_messages = json.loads(task.get('product_manager_messages', '[]'))
            
            # 构建人工确认结果摘要
            from services.utils.confirmation_utils import generate_confirmation_summary
            
            # 使用新的简化数据结构直接构造确认摘要
            formatted_results = []
            for i, result in enumerate(confirmation_results):
                user_answer = result.get('user_answer', '')
                
                # 调试信息：打印每个result的内容
                logger.info(f"处理确认结果 {i+1}: {result}")
                
                # 使用新的简化数据结构格式
                formatted_result = {
                    'question_details': result.get('question_details', f'确认项{i+1}'),
                    'user_answer': user_answer
                }
                
                # 调试信息：打印格式化后的结果
                logger.info(f"格式化结果 {i+1}: 问题详情长度={len(formatted_result['question_details'])}, 用户回答='{formatted_result['user_answer']}'")
                
                formatted_results.append(formatted_result)
            
            confirmation_summary = generate_confirmation_summary(formatted_results)
            
            # 添加用户指令：提供人工确认结果
            confirmation_message = f"""您之前的问题已经得到人工确认回答，以下是详细的确认结果：

{confirmation_summary}

请基于这些人工确认的结果，结合之前的原始PRD文档、需求分析和测试架构师的问题，生成最终完善的PRD文档。

要求：
1. 将所有人工确认的细节准确整合到对应的功能模块中
2. 确保确认结果与原始PRD和其他部分保持逻辑一致性
3. 在最终PRD文档中清楚标明哪些内容是基于人工确认补充的
4. 保持原始PRD的所有功能和业务逻辑
5. 形成完整、一致的业务逻辑闭环
"""
            
            product_manager_messages.append({
                'role': 'user',
                'content': confirmation_message
            })
            
            # 调用ProductManager AI
            response = strip_model_reasoning(product_manager.generate_reply(
                messages=product_manager_messages,
                sender=None
            ))
            
            # 将ProductManager的回复追加到对话历史
            product_manager_messages.append({
                'role': 'assistant',
                'content': response
            })
            
            # 保存对话历史到任务
            self.task_manager.update_task(task_id, **{
                'product_manager_messages': json.dumps(product_manager_messages, ensure_ascii=False),
                'current_phase': 'confirmation_integrated'
            })
            
            # 记录日志
            self.task_manager.add_log(
                task_id, 
                'INFO', 
                f"✅ 人工确认结果已发送给ProductManager，共{len(confirmation_results)}项确认"
            )
            
            self.notification_service.notify_log(
                task_id, 
                "✅ 人工确认结果已发送给ProductManager，AI正在整合确认结果..."
            )
            
            return {
                'success': True,
                'message': f'人工确认结果已发送给ProductManager，共{len(confirmation_results)}项',
                'confirmation_count': len(confirmation_results)
            }
            
        except Exception as e:
            logger.error(f"发送确认结果给ProductManager失败: {str(e)}")
            return {
                'success': False,
                'error': f'发送确认结果失败: {str(e)}'
            }
    
    def _initialize_agent_conversations(self, task_id):
        """初始化各Agent的对话历史
        
        基于DeepSeek示例模式：
        - 每个Agent维护独立的messages数组
        - 使用messages.append({'role': 'user', 'content': xxx})添加用户输入
        - 使用messages.append({'role': 'assistant', 'content': xxx})添加AI回复
        """
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        
        # 初始化ProductManager对话历史
        if not task.get('product_manager_messages'):
            self.task_manager.update_task(task_id, **{
                'product_manager_messages': json.dumps([], ensure_ascii=False)
            })
        
        # 初始化TestArchitect对话历史  
        if not task.get('test_architect_messages'):
            self.task_manager.update_task(task_id, **{
                'test_architect_messages': json.dumps([], ensure_ascii=False)
            })
            
        # 初始化 ModuleTestCaseWriter 对话历史（沿用历史字段名）
        if not task.get('test_case_writer_messages'):
            self.task_manager.update_task(task_id, **{
                'test_case_writer_messages': json.dumps([], ensure_ascii=False)
            })
        
        # 设置当前阶段
        self.task_manager.update_task(task_id, **{
            'current_phase': 'init'
        })
        
        self.task_manager.add_log(
            task_id, 'INFO',
            '✅ Agent对话历史初始化完成',
            {
                'step': '初始化',
                'action': '对话历史初始化',
                'component': 'GenerationService',
                'details': '所有Agent的messages数组已准备就绪'
            }
        )
    
    def _execute_product_enhancement_phase(self, task_id):
        """执行ProductManager优化PRD阶段
        
        对话模式：
        User: "请优化以下PRD文档：\n\n{prd_content}"
        ProductManager: enhanced_prd_response
        """
        task = self.task_manager.get_task(task_id)
        if not task:
            raise Exception("任务不存在")
        
        phase1_start = time.time()
        self.task_manager.update_task_status(
            task_id, 'product_enhancement', 10, 
            "🔍 阶段1：ProductManager优化PRD - 等待用户继续下一阶段")
        
        self.task_manager.add_log(
            task_id, 'INFO',
            '🔍 阶段1已准备：ProductManager PRD优化',
            {
                'step': '阶段1',
                'action': 'PRD优化准备',
                'component': 'ProductManager',
                'progress': 10,
                'details': 'ProductManager已准备好优化PRD，等待用户触发',
                'next_step': '用户需要调用execute_phase API继续'
            }
        )
        
        self.notification_service.notify_log(task_id, "\n" + "="*70)
        self.notification_service.notify_log(task_id, "🔍 阶段1已准备：ProductManager优化PRD")
        self.notification_service.notify_log(task_id, "请调用execute_phase API继续下一阶段")
        self.notification_service.notify_log(task_id, "="*70)
        
        return True
    
    def execute_phase(self, task_id, phase_name, user_input=None):
        """执行指定的任务阶段 - 基于用户控制的DeepSeek对话模式
        
        Args:
            task_id: 任务ID
            phase_name: 阶段名称 (product_enhancement, test_architect_qa, etc.)
            user_input: 用户输入内容（可选）
            
        Returns:
            dict: 执行结果
        """
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                return {
                    'success': False,
                    'error': f'任务 {task_id} 不存在'
                }
            
            # 根据阶段名称执行相应的方法
            if phase_name == 'product_enhancement':
                return self._execute_product_enhancement_with_ai(task_id)
            elif phase_name == 'test_architect_qa':
                return self._execute_test_architect_qa_with_ai(task_id)
            elif phase_name == 'product_manager_answer':
                return self._execute_product_manager_answer_with_ai(task_id)
            elif phase_name == 'human_confirmation':
                return self._execute_human_confirmation_phase(task_id, user_input)
            elif phase_name == 'final_prd_generation':
                return self._execute_final_prd_generation_with_ai(task_id)
            elif phase_name == 'test_case_generation':
                return self._execute_test_case_generation_with_ai(task_id)
            else:
                return {
                    'success': False,
                    'error': f'未知的阶段名称: {phase_name}'
                }
                
        except Exception as e:
            logger.error(f"执行阶段 {phase_name} 异常: {str(e)}")
            return {
                'success': False,
                'error': f'执行阶段失败: {str(e)}'
            }
    
    def _execute_product_enhancement_with_ai(self, task_id):
        """阶段1：ProductManager优化PRD - 实际调用AI"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}
        
        try:
            # 获取ProductManager智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents or 'product_manager' not in agents:
                return {'success': False, 'error': 'ProductManager智能体未初始化'}
            
            product_manager = agents['product_manager']
            
            # 获取ProductManager的对话历史
            product_manager_messages = json.loads(task.get('product_manager_messages', '[]'))
            logger.info(f"ProductManager阶段开始时对话历史数量: {len(product_manager_messages)}")
            
            # 添加用户指令：要求优化PRD
            prd_content = task.get('prd_content', '')
            logger.info(f"获取到PRD内容长度: {len(prd_content)}")
            logger.debug(f"PRD内容前200字符: {prd_content[:200]}")
            
            product_manager_messages.append({
                'role': 'user', 
                'content': f"请优化以下PRD文档，提供更详细和完整的需求描述：\n\n{prd_content}"
            })
            logger.info(f"添加用户消息后对话历史数量: {len(product_manager_messages)}")
            
            # 调用ProductManager AI
            response = strip_model_reasoning(product_manager.generate_reply(
                messages=product_manager_messages,
                sender=None
            ))
            logger.info(f"ProductManager生成回复长度: {len(response)}")
            
            # 将ProductManager的回复追加到对话历史（DeepSeek模式）
            product_manager_messages.append({
                'role': 'assistant', 
                'content': response
            })
            logger.info(f"添加AI回复后对话历史数量: {len(product_manager_messages)}")
            
            # 检查最终消息结构
            for i, msg in enumerate(product_manager_messages):
                logger.debug(f"消息{i}: role={msg.get('role')}, content长度={len(msg.get('content', ''))}")
            
            # 保存对话历史到任务
            messages_json = json.dumps(product_manager_messages, ensure_ascii=False)
            logger.info(f"准备保存的JSON长度: {len(messages_json)}")
            logger.debug(f"准备保存的JSON前200字符: {messages_json[:200]}")
            
            self.task_manager.update_task(task_id, **{
                'product_manager_messages': messages_json,
                'current_phase': 'product_enhancement'
            })
            logger.info("对话历史保存完成")
            
            # 检查是否有人工确认项目（阶段1只提取不保存，由阶段3统一处理）
            confirmation_items = self.analysis_service._extract_confirmation_items(response)
            logger.info(f"阶段1中提取到 {len(confirmation_items)} 个确认项，等待阶段3统一处理")
            
            # 注意：阶段1不在此处保存确认项到数据库，而是通过返回值传递给主流程
            
            # 更新任务状态（完成阶段1）
            self.task_manager.update_task_status(
                task_id, 'product_enhancement_completed', 20, 
                "✅ 阶段1完成：ProductManager已优化PRD")
            
            return {
                'success': True,
                'enhanced_prd': response,
                'confirmation_items': confirmation_items,
                'next_phase': 'test_architect_qa',
                'message': '产品经理已完成PRD优化'
            }
            
        except Exception as e:
            logger.error(f"ProductManager优化PRD失败: {str(e)}")
            return {
                'success': False,
                'error': f'PRD优化失败: {str(e)}'
            }
    
    def _execute_test_architect_qa_with_ai(self, task_id):
        """阶段2：TestArchitect提问 - 实际调用AI"""
        # 强制重新获取任务数据，避免缓存问题
        task = self.task_manager.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}
        
        try:
            # 获取TestArchitect智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents or 'test_architect' not in agents:
                return {'success': False, 'error': 'TestArchitect智能体未初始化'}
            
            test_architect = agents['test_architect']
            
            # 获取优化后的PRD（从ProductManager的最后一次回复中获取）
            pm_messages_raw = task.get('product_manager_messages', '[]')
            logger.info(f"获取到product_manager_messages原始数据: {type(pm_messages_raw)}, 长度: {len(str(pm_messages_raw))}")
            logger.debug(f"product_manager_messages前200字符: {str(pm_messages_raw)[:200]}")
            
            try:
                pm_messages = json.loads(pm_messages_raw)
                logger.info(f"解析product_manager_messages成功，消息数量: {len(pm_messages)}")
            except json.JSONDecodeError as e:
                logger.error(f"解析product_manager_messages失败: {e}")
                return {'success': False, 'error': f'解析产品经理对话历史失败: {str(e)}'}
            
            enhanced_prd = ""
            for i, msg in enumerate(reversed(pm_messages)):
                logger.debug(f"检查消息 {i}: role={msg.get('role')}, content长度={len(msg.get('content', ''))}")
                if msg.get('role') == 'assistant':
                    enhanced_prd = msg.get('content', '')
                    logger.info(f"找到ProductManager回复，内容长度: {len(enhanced_prd)}")
                    break
            
            if not enhanced_prd:
                logger.error(f"未找到ProductManager的assistant回复，消息列表: {[msg.get('role') for msg in pm_messages]}")
                return {'success': False, 'error': '未找到优化后的PRD'}
            
            # 从ProductManager回复中提取纯净的PRD文档内容（基于标记）
            cleaned_prd = self._extract_prd_from_marked_response(enhanced_prd)
            logger.info(f"提取的PRD文档内容长度: {len(cleaned_prd)}")
            
            # 获取TestArchitect的对话历史
            test_architect_messages = json.loads(task.get('test_architect_messages', '[]'))
            
            # 添加用户指令：要求基于PRD提问
            test_architect_messages.append({
                'role': 'user',
                'content': f"请基于以下PRD文档提出测试相关的问题，帮助完善需求理解：\n\n{cleaned_prd}"
            })
            
            # 调用TestArchitect AI
            response = strip_model_reasoning(test_architect.generate_reply(
                messages=test_architect_messages,
                sender=None
            ))
            
            # 将TestArchitect的回复追加到对话历史
            test_architect_messages.append({
                'role': 'assistant',
                'content': response
            })
            
            # 保存对话历史到任务
            self.task_manager.update_task(task_id, **{
                'test_architect_messages': json.dumps(test_architect_messages, ensure_ascii=False),
                'current_phase': 'test_architect_qa'
            })
            
            # 更新任务状态（完成阶段2）
            self.task_manager.update_task_status(
                task_id, 'test_architect_qa_completed', 30, 
                "✅ 阶段2完成：TestArchitect已提问")
            
            return {
                'success': True,
                'questions': response,
                'next_phase': 'product_manager_answer',
                'message': '测试架构师已提出问题'
            }
            
        except Exception as e:
            logger.error(f"TestArchitect提问失败: {str(e)}")
            return {
                'success': False,
                'error': f'TestArchitect提问失败: {str(e)}'
            }
    
    def _execute_product_manager_answer_with_ai(self, task_id):
        """阶段3：ProductManager回答问题 - 实际调用AI"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}
        
        try:
            # 获取ProductManager智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents or 'product_manager' not in agents:
                return {'success': False, 'error': 'ProductManager智能体未初始化'}
            
            product_manager = agents['product_manager']
            
            # 获取TestArchitect的问题
            ta_messages = json.loads(task.get('test_architect_messages', '[]'))
            questions = ""
            for msg in reversed(ta_messages):
                if msg.get('role') == 'assistant':
                    questions = msg.get('content', '')
                    break
            
            if not questions:
                return {'success': False, 'error': '未找到TestArchitect的问题'}
            
            # 获取ProductManager的对话历史
            product_manager_messages = json.loads(task.get('product_manager_messages', '[]'))
            
            # 添加用户指令：要求ProductManager回答TestArchitect的问题
            product_manager_messages.append({
                'role': 'user',
                'content': f"请回答测试架构师的以下问题。如果有不确定或需要进一步确认的内容，请打上人工确认标记：\n\n{questions}"
            })
            
            # 调用ProductManager AI
            response = strip_model_reasoning(product_manager.generate_reply(
                messages=product_manager_messages,
                sender=None
            ))
            
            # 将ProductManager的回复追加到对话历史
            product_manager_messages.append({
                'role': 'assistant',
                'content': response
            })
            
            # 保存对话历史到任务
            self.task_manager.update_task(task_id, **{
                'product_manager_messages': json.dumps(product_manager_messages, ensure_ascii=False),
                'current_phase': 'product_manager_answer'
            })
            
            # 检查是否有人工确认项目（阶段3只提取，不处理，由主流程统一处理）
            new_confirmation_items = self.analysis_service._extract_confirmation_items(response)
            logger.info(f"阶段3中提取到 {len(new_confirmation_items)} 个新确认项")
            
            # 注意：不在此处处理确认项的合并和保存，而是通过返回值传递给主流程
            
            # 更新任务状态（阶段3完成，确认项处理交给主流程）
            self.task_manager.update_task_status(
                task_id, 'product_manager_answer_completed', 40, 
                "✅ 阶段3完成：ProductManager已回答问题")
            
            return {
                'success': True,
                'answers': response,
                'confirmation_items': new_confirmation_items,  # 返回给主流程处理
                'next_phase': 'confirmation_check',  # 由主流程决定下一步
                'message': 'ProductManager已回答问题'
            }
            
        except Exception as e:
            logger.error(f"ProductManager回答问题失败: {str(e)}")
            return {
                'success': False,
                'error': f'ProductManager回答失败: {str(e)}'
            }
    
    def _execute_human_confirmation_phase(self, task_id, confirmations):
        """阶段4：处理人工确认"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}
        
        try:
            # 获取ProductManager智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents or 'product_manager' not in agents:
                return {'success': False, 'error': 'ProductManager智能体未初始化'}
            
            product_manager = agents['product_manager']
            
            # 获取ProductManager的对话历史
            product_manager_messages = json.loads(task.get('product_manager_messages', '[]'))
            
            # 构建确认结果内容
            confirmation_results = []
            for item in confirmations:
                confirmation_results.append(f"确认项目：{item['content']}\n用户决定：{item['decision']}")
            
            confirmation_content = "\n\n".join(confirmation_results)
            
            # 添加用户指令：提供确认结果，要求更新回答
            product_manager_messages.append({
                'role': 'user',
                'content': f"以下是人工确认的结果：\n\n{confirmation_content}\n\n请基于这些确认结果更新你之前的回答。"
            })
            
            # 调用ProductManager AI
            response = strip_model_reasoning(product_manager.generate_reply(
                messages=product_manager_messages,
                sender=None
            ))
            
            # 将ProductManager的回复追加到对话历史
            product_manager_messages.append({
                'role': 'assistant',
                'content': response
            })
            
            # 保存对话历史到任务
            self.task_manager.update_task(task_id, **{
                'product_manager_messages': json.dumps(product_manager_messages, ensure_ascii=False),
                'current_phase': 'human_confirmation'
            })
            
            # 更新任务状态
            self.task_manager.update_task_status(
                task_id, 'final_prd_generation', 60, 
                "✅ 阶段4完成：人工确认处理完成，准备生成最终PRD")
            
            return {
                'success': True,
                'updated_answers': response,
                'next_phase': 'final_prd_generation',
                'message': '人工确认处理完成'
            }
            
        except Exception as e:
            logger.error(f"人工确认处理失败: {str(e)}")
            return {
                'success': False,
                'error': f'人工确认处理失败: {str(e)}'
            }
    
    def _execute_final_prd_generation_with_confirmation(self, task_id):
        """阶段5：ProductManager整合人工确认结果并生成最终PRD（合并原阶段4.5和5）"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}
        
        try:
            # 获取ProductManager智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents or 'product_manager' not in agents:
                return {'success': False, 'error': 'ProductManager智能体未初始化'}
            
            product_manager = agents['product_manager']
            
            # 获取ProductManager的对话历史
            product_manager_messages = json.loads(task.get('product_manager_messages', '[]'))
            
            # 获取人工确认结果
            confirmation_results_str = task.get('confirmation_results', '[]')
            logger.info(f"获取到的confirmation_results_str: {type(confirmation_results_str)}, 内容: {str(confirmation_results_str)[:200]}")
            
            try:
                if isinstance(confirmation_results_str, str):
                    confirmation_results = json.loads(confirmation_results_str)
                else:
                    confirmation_results = confirmation_results_str or []
                
                logger.info(f"解析后的confirmation_results: {type(confirmation_results)}, 长度: {len(confirmation_results) if isinstance(confirmation_results, list) else 'N/A'}")
                
                if not confirmation_results:
                    logger.error(f"没有找到确认结果 - task字段: {list(task.keys())}")
                    return {'success': False, 'error': '没有找到确认结果'}
                    
            except json.JSONDecodeError as e:
                logger.error(f"解析confirmation_results失败: {e}, 原始数据: {confirmation_results_str}")
                return {'success': False, 'error': f'解析确认结果失败: {str(e)}'}
            
            # 构建人工确认结果摘要
            from services.utils.confirmation_utils import generate_confirmation_summary
            
            # 使用新的简化数据结构直接构造确认摘要
            formatted_results = []
            for i, result in enumerate(confirmation_results):
                user_answer = result.get('user_answer', '')
                
                # 调试信息：打印每个result的内容
                logger.info(f"处理确认结果 {i+1}: {result}")
                
                # 使用新的简化数据结构格式
                formatted_result = {
                    'question_details': result.get('question_details', f'确认项{i+1}'),
                    'user_answer': user_answer
                }
                
                # 调试信息：打印格式化后的结果
                logger.info(f"格式化结果 {i+1}: 问题详情长度={len(formatted_result['question_details'])}, 用户回答='{formatted_result['user_answer']}'")
                
                formatted_results.append(formatted_result)
            
            confirmation_summary = generate_confirmation_summary(formatted_results)
            
            # 构建综合指令：整合人工确认结果并生成最终PRD
            final_instruction = f"""基于以上所有对话内容，现在请整合人工确认结果并生成最终的完整PRD文档。

人工确认详情：
{confirmation_summary}

请基于：
1. 原始PRD文档
2. 你之前的需求分析和优化
3. 测试架构师的问题
4. 你之前的回答
5. 以上人工确认的结果

生成最终完善的PRD文档。要求比上一次优化后的PRD文档更完善。逻辑更完整，功能更完整，业务更完整。
请直接生成最终的完整PRD文档。"""
            
            # 添加综合指令到对话历史
            product_manager_messages.append({
                'role': 'user',
                'content': final_instruction
            })
            
            # 调用ProductManager AI生成最终PRD
            response = strip_model_reasoning(product_manager.generate_reply(
                messages=product_manager_messages,
                sender=None
            ))
            
            # 将ProductManager的回复追加到对话历史
            product_manager_messages.append({
                'role': 'assistant',
                'content': response
            })
            
            # 保存对话历史和最终PRD到任务
            self.task_manager.update_task(task_id, **{
                'product_manager_messages': json.dumps(product_manager_messages, ensure_ascii=False),
                'final_prd': response,  # 保存最终PRD
                'current_phase': 'final_prd_with_confirmation'
            })
            
            # 记录日志
            self.task_manager.add_log(
                task_id, 
                'INFO', 
                f"✅ 最终PRD生成完成，已整合{len(confirmation_results)}项人工确认"
            )
            
            # 更新任务状态（完成最终PRD生成）
            self.task_manager.update_task_status(
                task_id, 'final_prd_completed', 75, 
                "✅ 阶段5完成：最终PRD生成完成")
            
            return {
                'success': True,
                'final_prd': response,
                'confirmation_count': len(confirmation_results),
                'next_phase': 'test_case_generation',
                'message': f'最终PRD生成完成，已整合{len(confirmation_results)}项人工确认'
            }
            
        except Exception as e:
            logger.error(f"最终PRD生成失败: {str(e)}")
            return {
                'success': False,
                'error': f'最终PRD生成失败: {str(e)}'
            }
    
    def _execute_test_case_generation_with_ai(self, task_id):
        """阶段6：ModuleTestCaseWriter 生成测试用例 - 委托给专门的测试生成服务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}
        
        try:
            # 调用专门的测试生成服务
            success = self.test_generation.generate_test_cases(
                task_id, 
                task, 
                self.notification_service
            )
            
            if success:
                # 获取更新后的任务信息
                updated_task = self.task_manager.get_task(task_id)
                test_cases = updated_task.get('testcases', [])  # 使用数据库中的字段名
                
                # 更新任务状态（完成所有阶段）
                self.task_manager.update_task_status(
                    task_id, 'completed', 100, 
                    f"✅ 所有阶段完成：生成了{len(test_cases)}个测试用例")
                
                # 获取完整的AI回复内容
                test_case_writer_messages = json.loads(updated_task.get('test_case_writer_messages', '[]'))
                full_response = self._combine_test_case_responses(test_case_writer_messages)
                
                return {
                    'success': True,
                    'test_case_writer_response': full_response,
                    'test_cases': test_cases,
                    'next_phase': 'completed',
                    'message': f'测试用例生成完成，共{len(test_cases)}个用例'
                }
            else:
                # 没有生成任何测试用例
                self.task_manager.update_task_status(
                    task_id, 'failed', 75, 
                    "❌ 测试用例生成失败：未能生成有效的测试用例")
                
                return {
                    'success': False,
                    'error': '未能生成有效的测试用例'
                }
            
        except Exception as e:
            logger.error(f"测试用例生成失败: {str(e)}")
            return {
                'success': False,
                'error': f'测试用例生成失败: {str(e)}'
            }
    
    def _combine_test_case_responses(self, test_case_writer_messages):
        """合并所有轮次的 ModuleTestCaseWriter 回复内容
        
        Args:
            test_case_writer_messages: ModuleTestCaseWriter 的完整对话历史
            
        Returns:
            str: 合并后的完整回复内容
        """
        try:
            assistant_responses = []
            for msg in test_case_writer_messages:
                if msg.get('role') == 'assistant':
                    content = msg.get('content', '')
                    if content.strip():
                        assistant_responses.append(content)
            
            if assistant_responses:
                # 用分隔符连接所有回复
                combined_response = "\n\n" + "="*50 + " 测试用例生成记录 " + "="*50 + "\n\n"
                
                for i, response in enumerate(assistant_responses, 1):
                    combined_response += f"## 第{i}轮生成结果\n\n{response}\n\n"
                
                combined_response += "="*50 + " 生成完成 " + "="*50 + "\n"
                return combined_response
            else:
                return "未找到测试用例生成内容"
                
        except Exception as e:
            logger.error(f"合并ModuleTestCaseWriter回复异常: {str(e)}")
            return f"合并回复时发生错误: {str(e)}"
        
    def process_human_confirmation(self, task_id, confirmation_results):
        """处理人工确认结果
        
        Args:
            task_id: 任务ID
            confirmation_results: 确认结果列表
            
        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            # 检查任务是否存在
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"处理人工确认失败: 任务 {task_id} 不存在")
                return False
            
            # 更新任务状态
            self.task_manager.update_task_status(
                task_id, 
                'processing', 
                60, 
                "处理人工确认结果")
            
            # 记录日志
            self.task_manager.add_log(
                task_id,
                'INFO',
                f"收到人工确认回答，共 {len(confirmation_results)} 项"
            )
            
            # 发送通知
            self.notification_service.notify_confirmation_received(
                task_id, 
                len(confirmation_results)
            )
            
            # 创建线程继续执行任务
            threading.Thread(
                target=self._continue_after_confirmation,
                args=(task_id,),
                daemon=True
            ).start()
            
            return True
            
        except Exception as e:
            logger.error(f"处理人工确认异常: {str(e)}")
            return False
            
    def _continue_after_confirmation(self, task_id):
        """人工确认后继续自动执行剩余阶段
        
        Args:
            task_id: 任务ID
        """
        try:
            # 更新任务状态
            self.task_manager.update_task_status(
                task_id, 
                'processing', 
                60, 
                "✅ 人工确认处理完成，继续自动执行")
            
            # 记录日志
            self.task_manager.add_log(
                task_id,
                'INFO',
                "✅ 人工确认处理完成，继续自动执行剩余阶段"
            )
            
            # 自动执行剩余阶段（阶段5: 最终PRD → 阶段6: 测试用例）
            self._continue_automatic_execution(task_id)
            
            return True
            
        except Exception as e:
            logger.error(f"人工确认后继续执行异常: {str(e)}")
            
            # 更新任务状态
            self.task_manager.update_task_status(
                task_id, 'failed', 0, 
                f"人工确认后继续执行失败: {str(e)}")
            
            # 发送通知
            self.notification_service.notify_error(task_id, f"人工确认后继续执行失败: {str(e)}")
            
            # 记录完整堆栈信息到日志
            logger.error(f"任务 {task_id} 人工确认后继续执行异常: {traceback.format_exc()}")
            return False
    
    def get_task_files(self, task_id, file_type=None):
        """获取任务相关文件"""
        try:
            # 获取任务信息
            task = self.task_manager.get_task(task_id)
            if not task:
                return []
                
            # 查找文件路径
            result_files = task.get('result_files', {})
            
            # 如果指定了文件类型，只返回该类型
            if file_type:
                if file_type in result_files:
                    file_path = result_files[file_type]
                    # 检查文件是否存在
                    if os.path.exists(file_path):
                        return [{
                            'id': f"{task_id}_{file_type}",
                            'name': os.path.basename(file_path),
                            'path': file_path,
                            'type': file_type,
                            'created_at': datetime.fromtimestamp(
                                os.path.getctime(file_path)
                            ).isoformat()
                        }]
                    else:
                        return []
                else:
                    return []
            
            # 返回所有文件
            files = []
            for file_type, file_path in result_files.items():
                # 检查文件是否存在
                if os.path.exists(file_path):
                    files.append({
                        'id': f"{task_id}_{file_type}",
                        'name': os.path.basename(file_path),
                        'path': file_path,
                        'type': file_type,
                        'created_at': datetime.fromtimestamp(
                            os.path.getctime(file_path)
                        ).isoformat()
                    })
            
            return files
        
        except Exception as e:
            logger.error(f"获取任务文件失败: {str(e)}")
            return []
    
    def export_task_file(self, task_id, file_type):
        """导出任务文件
        
        Args:
            task_id: 任务ID
            file_type: 文件类型 (excel, json, md, html)
            
        Returns:
            str: 文件路径，失败则返回None
        """
        files = self.get_task_files(task_id, file_type)
        if files and len(files) > 0:
            return files[0]['path']
        return None
    
    def _deduplicate_confirmation_items(self, confirmation_items):
        """去除重复的确认项
        
        Args:
            confirmation_items: 确认项列表
            
        Returns:
            list: 去重后的确认项列表
        """
        try:
            if not confirmation_items:
                return []
            
            seen_titles = set()
            deduplicated_items = []
            
            for item in confirmation_items:
                # 使用新的question_details字段提取标题
                question_details = item.get('question_details', '')
                
                # 从question_details中提取标题用于去重
                title = self._extract_confirmation_title_from_content(question_details)
                
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    deduplicated_items.append(item)
                else:
                    logger.info(f"跳过重复确认项: {title[:50]}...")
            
            logger.info(f"确认项去重: {len(confirmation_items)} -> {len(deduplicated_items)}")
            return deduplicated_items
            
        except Exception as e:
            logger.error(f"确认项去重失败: {e}")
            return confirmation_items  # 出错时返回原列表
    
    def _extract_confirmation_title_from_content(self, content):
        """从确认项内容中提取问题标题（与analysis_service中的方法一致）
        
        Args:
            content: 确认项内容
            
        Returns:
            str: 提取的标题，用于去重判断
        """
        try:
            import re
            
            # 尝试多种标题格式匹配
            title_patterns = [
                r'问题标题[：:]\s*(.+?)(?:\n|$)',
                r'\*\*问题标题\*\*[：:]\s*(.+?)(?:\n|$)',
                r'标题[：:]\s*(.+?)(?:\n|$)',
                r'^(.+?)(?:\n确认点|$)',  # 如果没有明确标题标记，取第一行
            ]
            
            for pattern in title_patterns:
                match = re.search(pattern, content.strip(), re.MULTILINE)
                if match:
                    title = match.group(1).strip()
                    # 清理标题中的markdown标记
                    title = re.sub(r'\*\*(.+?)\*\*', r'\1', title)
                    if title and len(title) > 5:  # 确保标题有意义
                        return title
            
            # 如果都无法匹配，使用内容前50字符作为标题
            return content[:50].strip()
            
        except Exception as e:
            logger.error(f"提取确认项标题失败: {e}")
            return content[:50].strip() if content else ""
    
    def _extract_prd_from_marked_response(self, pm_response):
        """从ProductManager的回复中提取标记内的PRD文档内容
        
        根据 <PRD_DOCUMENT_START> 和 <PRD_DOCUMENT_END> 标记提取纯净的PRD文档
        """
        try:
            prd_content = clean_prd_document(pm_response)
            if prd_content != str(pm_response or "").strip():
                logger.info(f"成功清理PRD文档，内容长度: {len(prd_content)}")
            else:
                logger.warning("未找到可清理的PRD包装，返回原始内容")
            return prd_content
                
        except Exception as e:
            logger.error(f"提取标记内PRD文档失败: {e}")
            # 如果提取失败，返回原内容
            return pm_response
