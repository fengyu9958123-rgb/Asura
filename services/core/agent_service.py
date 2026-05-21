"""
智能体管理服务
负责创建和管理智能体的生命周期
"""

import logging
from datetime import datetime
import time
import traceback
from services.generation.llm_response_cleaner import strip_model_reasoning

# 导入本地配置和智能体模块
try:
    from config import Config
    from agents import AgentFactory
except ImportError as e:
    logging.error(f"导入错误: {e}")
    logging.error("请确保已安装autogen并且项目结构正确")

logger = logging.getLogger(__name__)


class AgentService:
    """智能体管理服务，负责创建和管理智能体的生命周期"""

    def __init__(self, logging_service):
        """初始化服务"""
        self.logging_service = logging_service
        self.config_list = None
        self.agents = {}  # 存储不同会话的智能体
        self.current_session_id = None
        self.error_counts = {}  # 存储会话的错误计数
        self.retry_limits = {
            'initialization': 3,  # 初始化重试次数
            'generation': 2,      # 生成过程重试次数
            'message': 3          # 消息发送重试次数
        }

        # 尝试初始化配置
        try:
            config = Config()
            self.config_list = config.load_config()
            if self.config_list:
                logger.info("智能体配置加载成功")
                self.logging_service.log_system_event(
                    "配置加载",
                    "智能体配置加载成功"
                )

                # 创建智能体工厂
                self.agent_factory = AgentFactory(self.config_list, self.logging_service)
            else:
                logger.warning("未找到有效的智能体配置")
                self.logging_service.log_system_event(
                    "配置加载警告",
                    "未找到有效的智能体配置"
                )
                self.agent_factory = None
        except Exception as e:
            logger.error(f"智能体配置加载失败: {e}")
            self.logging_service.log_system_event(
                "配置加载错误",
                f"智能体配置加载失败: {str(e)}"
            )
            self.agent_factory = None

    def initialize_agents(self, session_id, mode="普通模式"):
        """初始化一组智能体 - 带重试机制"""
        if not self.config_list or not self.agent_factory:
            error_msg = "无法初始化智能体: 配置未加载或工厂未创建"
            logger.error(error_msg)
            self.logging_service.log_system_event("智能体初始化错误", error_msg)
            return False

        # 初始化错误计数
        self.error_counts[session_id] = {'initialization': 0, 'generation': 0, 'message': 0}

        # 添加重试机制
        retry_count = 0
        max_retries = self.retry_limits['initialization']

        while retry_count < max_retries:
            try:
                logger.info(f"正在为会话 {session_id} 初始化智能体 (尝试 {retry_count+1}/{max_retries})...")
                self.logging_service.log_system_event(
                    "智能体初始化",
                    f"正在为会话 {session_id} 初始化智能体 (尝试 {retry_count+1}/{max_retries})"
                )

                # 使用工厂创建所有智能体
                agents = self.agent_factory.create_all_agents(mode)
                if not agents:
                    raise ValueError("智能体创建失败，工厂返回空结果")

                # 检查智能体是否创建成功
                if not all([
                    agents.get('product_manager'),
                    agents.get('test_architect'),
                    agents.get('module_test_case_writer'),
                ]):
                    raise ValueError("部分智能体创建失败")

                # 存储智能体
                self.agents[session_id] = {
                    **agents,
                    'initialized_time': datetime.now(),
                    'last_used': datetime.now(),
                    'health_status': 'healthy',
                    'error_history': [],
                    'mode': mode  # 保存使用的模式
                }

                # 设置当前会话ID
                self.current_session_id = session_id

                logger.info(f"会话 {session_id} 的智能体初始化成功")
                self.logging_service.log_system_event(
                    "智能体初始化成功",
                    f"会话 {session_id} 的智能体初始化成功"
                )
                return True

            except Exception as e:
                retry_count += 1
                error_detail = traceback.format_exc()
                self.error_counts[session_id]['initialization'] += 1

                # 记录错误
                error_msg = f"智能体初始化失败 (尝试 {retry_count}/{max_retries}): {str(e)}"
                logger.error(error_msg)
                logger.debug(f"错误详情: {error_detail}")

                # 记录错误历史
                if session_id in self.agents:
                    self.agents[session_id]['error_history'].append({
                        'type': 'initialization',
                        'error': str(e),
                        'detail': error_detail,
                        'time': datetime.now().isoformat(),
                        'attempt': retry_count
                    })

                self.logging_service.log_system_event(
                    "智能体初始化错误",
                    error_msg
                )

                # 等待后重试
                if retry_count < max_retries:
                    delay = retry_count * 2  # 逐步增加延迟
                    logger.info(f"等待 {delay} 秒后重试...")
                    time.sleep(delay)

        # 所有重试都失败
        logger.error(f"会话 {session_id} 的智能体初始化失败，已达到最大重试次数 {max_retries}")
        self.logging_service.log_system_event(
            "智能体初始化最终失败",
            f"会话 {session_id} 的智能体初始化失败，已达到最大重试次数 {max_retries}"
        )
        return False

    def get_agents(self, session_id):
        """获取指定会话的智能体"""
        if session_id not in self.agents:
            logger.warning(f"会话 {session_id} 的智能体未初始化")

            # 尝试自动初始化
            logger.info(f"尝试自动初始化会话 {session_id} 的智能体")
            if self.initialize_agents(session_id, "普通模式"):  # 使用默认模式
                logger.info(f"自动初始化会话 {session_id} 的智能体成功")
                self.logging_service.log_system_event(
                    "智能体初始化",
                    f"自动初始化会话 {session_id} 的智能体成功"
                )
                return self.agents.get(session_id)
            else:
                logger.error(f"自动初始化会话 {session_id} 的智能体失败")
                self.logging_service.log_system_event(
                    "智能体初始化错误",
                    f"自动初始化会话 {session_id} 的智能体失败"
                )
                return None

        try:
            # 更新最后使用时间
            self.agents[session_id]['last_used'] = datetime.now()

            # 检查健康状态
            if self.agents[session_id].get('health_status') == 'unhealthy':
                logger.warning(f"会话 {session_id} 的智能体状态不健康，尝试恢复")
                self._attempt_recovery(session_id)

            # 验证所有必要的智能体都存在
            required_agents = [
                'product_manager',
                'test_architect',
                'module_test_case_writer',
                'prd_block_builder',
                'prd_knowledge_builder',
            ]
            missing_agents = []
            for agent_name in required_agents:
                if agent_name not in self.agents[session_id] or self.agents[session_id][agent_name] is None:
                    missing_agents.append(agent_name)

            # 如果有缺失的智能体，尝试重新创建
            if missing_agents:
                logger.warning(f"会话 {session_id} 缺少智能体: {', '.join(missing_agents)}，尝试恢复")
                if not self._attempt_recovery(session_id):
                    logger.error(f"无法恢复会话 {session_id} 的智能体")
                    return None

            # 验证智能体是否有日志记录功能
            for agent_name in required_agents:
                agent = self.agents[session_id].get(agent_name)
                if agent:
                    # 检查是否需要添加任务消息记录（避免重复包装）
                    if (not hasattr(agent, '_task_logging_added') and
                        hasattr(agent, 'generate_reply')):
                        logger.info(f"为智能体 {agent_name} 添加任务消息记录功能")
                        self.add_task_logging_to_agent(agent, agent_name, session_id)

            return self.agents[session_id]
        except Exception as e:
            logger.error(f"获取智能体异常: {e}")
            self.logging_service.log_system_event("智能体获取错误", f"获取会话 {session_id} 的智能体时发生异常: {str(e)}")
            return None

    def add_task_logging_to_agent(self, agent, agent_name, session_id):
        """为智能体添加任务消息记录功能（不重复日志记录）"""
        try:
            if not agent:
                return

            # 添加生成回复的任务消息记录（避免与factory.py重复记录日志，但保留任务消息）
            if hasattr(agent, 'generate_reply'):
                original_generate_reply = agent.generate_reply
                def generate_reply_with_task_logging(messages, sender=None, **kwargs):
                    try:
                        reply = original_generate_reply(messages, sender, **kwargs)
                        reply = strip_model_reasoning(reply)
                        # 只记录任务消息到数据库，不记录详细日志（避免重复）
                        if hasattr(self, 'task_manager'):
                            self.task_manager.add_message(
                                session_id,
                                agent_name,
                                reply  # 移除500字符截断限制，保存完整内容
                            )
                        return reply
                    except Exception as e:
                        logger.error(f"{agent_name}生成回复异常: {e}")
                        return f"生成回复时发生错误: {str(e)}"
                agent.generate_reply = generate_reply_with_task_logging

                # 标记已添加任务日志记录，避免重复添加
                agent._task_logging_added = True

            logger.info(f"成功为{agent_name}添加任务消息记录功能")

        except Exception as e:
            logger.error(f"为{agent_name}添加任务消息记录功能失败: {e}")

    def add_logging_to_agent(self, agent, agent_name, session_id):
        """为智能体添加日志记录功能（已弃用，保留以防向后兼容）"""
        logger.warning(f"add_logging_to_agent已弃用，使用add_task_logging_to_agent代替")
        self.add_task_logging_to_agent(agent, agent_name, session_id)

    def _attempt_recovery(self, session_id):
        """尝试恢复不健康的智能体"""
        if session_id not in self.agents:
            return False

        try:
            # 检查不健康的智能体数量
            unhealthy_agents = []
            agent_instances = self.agents[session_id]

            managed_agents = [
                'product_manager',
                'test_architect',
                'module_test_case_writer',
                'prd_block_builder',
                'prd_knowledge_builder',
            ]

            for agent_name in managed_agents:
                if agent_name not in agent_instances or agent_instances[agent_name] is None:
                    unhealthy_agents.append(agent_name)

            # 如果全部都有问题，可能需要完全重新初始化
            if len(unhealthy_agents) == len(managed_agents):
                logger.info(f"会话 {session_id} 的所有智能体都不健康，尝试重新初始化")
                return self.clear_agent_history(session_id)

            # 否则，仅重新创建不健康的智能体
            saved_mode = agent_instances.get('mode', '普通模式')  # 获取原有模式
            for agent_name in unhealthy_agents:
                logger.info(f"重新创建会话 {session_id} 的 {agent_name}")

                if agent_name == 'product_manager':
                    agent_instances['product_manager'] = self.agent_factory.create_product_manager(saved_mode)
                elif agent_name == 'test_architect':
                    agent_instances['test_architect'] = self.agent_factory.create_test_architect(saved_mode)
                elif agent_name == 'module_test_case_writer':
                    agent_instances['module_test_case_writer'] = self.agent_factory.create_module_test_case_writer()
                elif agent_name == 'integration_test_case_writer':
                    agent_instances['integration_test_case_writer'] = self.agent_factory.create_integration_test_case_writer()
                elif agent_name == 'prd_block_builder':
                    agent_instances['prd_block_builder'] = self.agent_factory.create_prd_block_builder()
                elif agent_name == 'prd_knowledge_builder':
                    agent_instances['prd_knowledge_builder'] = self.agent_factory.create_prd_knowledge_builder()

            # 更新健康状态
            agent_instances['health_status'] = 'recovering'

            self.logging_service.log_system_event(
                "智能体恢复",
                f"会话 {session_id} 的智能体已尝试恢复"
            )

            return True

        except Exception as e:
            logger.error(f"智能体恢复失败: {e}")
            self.logging_service.log_system_event(
                "智能体恢复失败",
                f"会话 {session_id} 的智能体恢复失败: {str(e)}"
            )
            return False

    def clear_agent_history(self, session_id):
        """清空指定会话的智能体历史"""
        if session_id not in self.agents:
            logger.warning(f"会话 {session_id} 的智能体不存在")
            return False

        try:
            logger.info(f"正在清空会话 {session_id} 的智能体历史")
            self.logging_service.log_system_event(
                "清空智能体历史",
                f"正在清空会话 {session_id} 的智能体历史"
            )

            # 保存错误历史和模式
            error_history = self.agents[session_id].get('error_history', [])
            saved_mode = self.agents[session_id].get('mode', '普通模式')

            # 重新初始化智能体 (删除旧的，创建新的)
            del self.agents[session_id]

            # 重新初始化
            success = self.initialize_agents(session_id, saved_mode)

            # 恢复错误历史
            if success and session_id in self.agents:
                self.agents[session_id]['error_history'] = error_history

            return success

        except Exception as e:
            logger.error(f"清空智能体历史失败: {e}")
            self.logging_service.log_system_event(
                "清空智能体历史错误",
                f"清空智能体历史失败: {str(e)}"
            )
            return False

    def send_message_with_retry(self, session_id, agent_name, message, recipient=None):
        """发送消息带重试机制"""
        if session_id not in self.agents:
            logger.warning(f"会话 {session_id} 的智能体未初始化")
            return None

        agent_dict = self.agents[session_id]
        if agent_name not in agent_dict or agent_dict[agent_name] is None:
            logger.warning(f"会话 {session_id} 中不存在智能体 {agent_name}")
            return None

        agent = agent_dict[agent_name]
        retry_count = 0
        max_retries = self.retry_limits['message']

        while retry_count < max_retries:
            try:
                logger.info(f"发送消息 (尝试 {retry_count+1}/{max_retries})...")

                # 根据是否有接收者决定使用哪个方法
                if recipient:
                    response = agent.send(
                        recipient=recipient,
                        message=message
                    )
                else:
                    response = strip_model_reasoning(agent.generate_reply(
                        messages=[
                            {"role": "user", "content": message}
                        ]
                    ))

                # 更新健康状态
                agent_dict['health_status'] = 'healthy'

                return response

            except Exception as e:
                retry_count += 1
                error_detail = traceback.format_exc()
                self.error_counts[session_id]['message'] += 1

                # 记录错误
                error_msg = f"发送消息失败 (尝试 {retry_count}/{max_retries}): {str(e)}"
                logger.error(error_msg)
                logger.debug(f"错误详情: {error_detail}")

                # 记录错误历史
                agent_dict['error_history'].append({
                    'type': 'message_send',
                    'agent': agent_name,
                    'error': str(e),
                    'detail': error_detail,
                    'time': datetime.now().isoformat(),
                    'attempt': retry_count
                })

                # 标记健康状态
                if retry_count >= max_retries - 1:
                    agent_dict['health_status'] = 'unhealthy'

                self.logging_service.log_system_event(
                    "发送消息错误",
                    error_msg
                )

                # 等待后重试
                if retry_count < max_retries:
                    delay = retry_count * 2  # 逐步增加延迟
                    logger.info(f"等待 {delay} 秒后重试...")
                    time.sleep(delay)

        # 所有重试都失败
        logger.error(f"会话 {session_id} 的消息发送失败，已达到最大重试次数 {max_retries}")
        self.logging_service.log_system_event(
            "发送消息最终失败",
            f"会话 {session_id} 的消息发送失败，已达到最大重试次数 {max_retries}"
        )
        return None

    def get_agent_health_status(self, session_id):
        """获取智能体健康状态"""
        if session_id not in self.agents:
            return {
                'status': 'not_initialized',
                'error_counts': {},
                'error_history': []
            }

        agent_dict = self.agents[session_id]

        # 计算错误率
        error_rates = {}
        if session_id in self.error_counts:
            total_operations = sum(self.error_counts[session_id].values()) + 1  # 防止除零
            error_rates = {
                k: round(v / total_operations * 100, 1)
                for k, v in self.error_counts[session_id].items()
            }

        # 构建健康状态报告
        health_report = {
            'status': agent_dict.get('health_status', 'unknown'),
            'error_counts': self.error_counts.get(session_id, {}),
            'error_rates': error_rates,
            'error_history': agent_dict.get('error_history', []),
            'last_used': agent_dict.get('last_used').isoformat() if agent_dict.get('last_used') and not isinstance(agent_dict.get('last_used'), str) else agent_dict.get('last_used'),
            'initialized_time': agent_dict.get('initialized_time').isoformat() if agent_dict.get('initialized_time') and not isinstance(agent_dict.get('initialized_time'), str) else agent_dict.get('initialized_time'),
            'agents_initialized': {
                'product_manager': agent_dict.get('product_manager') is not None,
                'test_architect': agent_dict.get('test_architect') is not None,
                'module_test_case_writer': agent_dict.get('module_test_case_writer') is not None,
                'integration_test_case_writer': agent_dict.get('integration_test_case_writer') is not None,
                'prd_block_builder': agent_dict.get('prd_block_builder') is not None,
                'prd_knowledge_builder': agent_dict.get('prd_knowledge_builder') is not None
            }
        }

        return health_report

    def cleanup_old_sessions(self, max_age_hours=24):
        """清理超过指定时间未使用的会话"""
        try:
            current_time = datetime.now()
            sessions_to_remove = []

            for session_id, agent_data in self.agents.items():
                # 获取最后使用时间，如果没有则使用初始化时间
                last_used = agent_data.get(
                    'last_used', agent_data.get('initialized_time'))
                age = (current_time - last_used).total_seconds() / 3600  # 小时

                if age > max_age_hours:
                    sessions_to_remove.append(session_id)

            # 删除过期会话
            for session_id in sessions_to_remove:
                # 保存错误统计和历史到日志
                if session_id in self.agents and len(self.agents[session_id].get('error_history', [])) > 0:
                    self.logging_service.log_system_event(
                        "会话错误统计",
                        f"会话 {session_id} 在生命周期内出现 {len(self.agents[session_id].get('error_history', []))} 个错误"
                    )

                # 删除会话数据
                del self.agents[session_id]
                if session_id in self.error_counts:
                    del self.error_counts[session_id]

                logger.info(f"已清理过期会话: {session_id}")
                self.logging_service.log_system_event(
                    "清理过期会话",
                    f"已清理过期会话: {session_id}"
                )

            return len(sessions_to_remove)
        except Exception as e:
            logger.error(f"清理过期会话失败: {e}")
            self.logging_service.log_system_event(
                "清理会话错误",
                f"清理过期会话失败: {str(e)}"
            )
            return 0
