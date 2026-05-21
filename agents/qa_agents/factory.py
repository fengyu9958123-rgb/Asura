"""
测试用例生成智能体工厂模块
专门负责创建测试用例生成相关的智能体
"""

import logging
from services.generation.llm_response_cleaner import strip_model_reasoning
from .templates.product_manager import create_product_manager, TEMPLATES as PM_TEMPLATES
from .templates.test_architect import create_test_architect, TEMPLATES as TA_TEMPLATES
from .templates.module_test_writer import create_module_test_case_writer, TEMPLATES as MTW_TEMPLATES
from .templates.integration_test_writer import create_integration_test_case_writer, TEMPLATES as ITW_TEMPLATES
from .templates.prd_block_builder import create_prd_block_builder, TEMPLATES as PBB_TEMPLATES
from .templates.prd_knowledge_builder import create_prd_knowledge_builder, TEMPLATES as PKB_TEMPLATES
from .templates.test_case_quality_reviewer import create_test_case_quality_reviewer, TEMPLATES as TCQR_TEMPLATES
from .templates.image_analyst import create_image_analyst, TEMPLATES as IA_TEMPLATES
from .templates.image_integration_analyst import create_image_integration_analyst, TEMPLATES as IIA_TEMPLATES
from .templates.image_prd_reviewer import create_image_prd_reviewer, TEMPLATES as IPR_TEMPLATES
from .templates.confirmation_integrator import create_confirmation_integrator, TEMPLATES as CI_TEMPLATES
from .templates.text_prd_logic_reviewer import create_text_prd_logic_reviewer, TEMPLATES as TPLR_TEMPLATES
from .templates.text_final_prd_integrator import create_text_final_prd_integrator, TEMPLATES as TFPI_TEMPLATES

logger = logging.getLogger(__name__)


class QAAgentFactory:
    """测试用例生成智能体工厂类，专门创建测试相关的智能体"""
    
    def __init__(self, config_list=None, logging_service=None):
        """
        初始化测试智能体工厂
        
        Args:
            config_list: LLM配置列表
            logging_service: 日志服务实例
        """
        self.config_list = config_list
        self.logging_service = logging_service
    
    def _add_logging_interceptors(self, agent):
        """
        为智能体添加消息拦截器，用于记录消息
        
        Args:
            agent: 智能体实例
            
        Returns:
            添加了消息拦截器的智能体
        """
        if not self.logging_service or not agent:
            return agent
        
        try:
            # 拦截发送消息
            original_send = agent.send
            def send_with_logging(message, recipient, request_reply=True, silent=False):
                try:
                    # 记录发送的消息
                    self.logging_service.log_ai_message(
                        agent.name, 
                        message, 
                        "发送消息",
                        recipient.name
                    )
                    
                    # 记录详细对话日志
                    self.logging_service.log_ai_chat_detail(
                        agent.name,
                        recipient.name,
                        message,
                        "发送消息"
                    )
                except Exception as e:
                    logger.error(f"记录消息失败: {e}")
                
                # 调用原始方法
                return original_send(message, recipient, request_reply, silent)
            
            # 替换方法
            agent.send = send_with_logging
            
            # 拦截接收消息
            original_receive = agent.receive
            def receive_with_logging(message, sender, request_reply=True, silent=False):
                try:
                    # 记录接收的消息
                    self.logging_service.log_ai_message(
                        agent.name, 
                        message, 
                        "接收消息",
                        sender.name
                    )
                    
                    # 记录详细对话日志
                    self.logging_service.log_ai_chat_detail(
                        sender.name,
                        agent.name,
                        message,
                        "接收消息"
                    )
                except Exception as e:
                    logger.error(f"记录消息失败: {e}")
                
                # 调用原始方法
                return original_receive(message, sender, request_reply, silent)
            
            # 替换方法
            agent.receive = receive_with_logging
            
            # 拦截生成回复
            original_generate_reply = agent.generate_reply
            def generate_reply_with_logging(messages, sender=None, **kwargs):
                try:
                    # 先记录接收到的消息
                    if messages and len(messages) > 0:
                        last_message = messages[-1]
                        if isinstance(last_message, dict) and "content" in last_message:
                            self.logging_service.log_ai_chat_detail(
                                last_message.get("role", "user"),
                                agent.name,
                                last_message.get("content", ""),
                                "接收消息"
                            )
                except Exception as e:
                    logger.error(f"记录接收消息失败: {e}")
                
                # 调用原始方法
                if sender is None:
                    reply = original_generate_reply(messages)
                else:
                    reply = original_generate_reply(messages, sender, **kwargs)
                reply = strip_model_reasoning(reply)
                
                try:
                    # 记录生成的回复
                    if reply:
                        sender_name = sender.name if sender and hasattr(sender, "name") else "系统"
                        self.logging_service.log_ai_message(
                            agent.name, 
                            reply, 
                            "生成回复",
                            sender_name
                        )
                except Exception as e:
                    logger.error(f"记录生成回复失败: {e}")
                
                return reply
            
            # 替换方法
            agent.generate_reply = generate_reply_with_logging
            
            logger.info(f"已为测试智能体 {agent.name} 添加消息拦截器")
            
        except Exception as e:
            logger.error(f"添加消息拦截器失败: {e}")
            
        return agent
        
    def create_product_manager(self, template_name="普通模式"):
        """
        创建产品经理智能体
        
        Args:
            template_name: 模板名称
            
        Returns:
            ProductManager智能体实例
        """
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建", 
                    f"创建产品经理智能体，模板: {template_name}"
                )
            
            # 创建智能体
            agent = create_product_manager(self.config_list, template_name)
            
            # 添加消息拦截器
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
                
            return agent
            
        except Exception as e:
            logger.error(f"创建产品经理智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建失败", 
                    f"创建产品经理智能体失败: {e}"
                )
            return None
            
    def create_test_architect(self, template_name="普通模式"):
        """
        创建测试架构师智能体
        
        Args:
            template_name: 模板名称
            
        Returns:
            TestArchitect智能体实例
        """
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建", 
                    f"创建测试架构师智能体，模板: {template_name}"
                )
            
            # 创建智能体
            agent = create_test_architect(self.config_list, template_name)
            
            # 添加消息拦截器
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
                
            return agent
            
        except Exception as e:
            logger.error(f"创建测试架构师智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建失败", 
                    f"创建测试架构师智能体失败: {e}"
                )
            return None
            
    def create_module_test_case_writer(self, template_name="模块包生成"):
        """创建模块测试包用例编写智能体"""
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建",
                    f"创建模块测试包用例编写智能体，模板: {template_name}"
                )
            agent = create_module_test_case_writer(self.config_list, template_name)
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
            logger.info(f"模块测试包用例编写智能体创建成功，模板: {template_name}")
            return agent
        except Exception as e:
            logger.error(f"创建模块测试包用例编写智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event("测试智能体创建失败", f"创建模块测试包用例编写智能体失败: {e}")
            return None

    def create_integration_test_case_writer(self, template_name="链路包生成"):
        """创建链路测试包用例编写智能体"""
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建",
                    f"创建链路测试包用例编写智能体，模板: {template_name}"
                )
            agent = create_integration_test_case_writer(self.config_list, template_name)
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
            logger.info(f"链路测试包用例编写智能体创建成功，模板: {template_name}")
            return agent
        except Exception as e:
            logger.error(f"创建链路测试包用例编写智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event("测试智能体创建失败", f"创建链路测试包用例编写智能体失败: {e}")
            return None

    def create_prd_block_builder(self, template_name="PRD分块"):
        """创建 PRD 分块智能体"""
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建",
                    f"创建 PRD 分块智能体，模板: {template_name}"
                )
            agent = create_prd_block_builder(self.config_list, template_name)
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
            logger.info(f"PRD 分块智能体创建成功，模板: {template_name}")
            return agent
        except Exception as e:
            logger.error(f"创建 PRD 分块智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event("测试智能体创建失败", f"创建 PRD 分块智能体失败: {e}")
            return None

    def create_prd_knowledge_builder(self, template_name="知识关系构建"):
        """创建 PRD 知识关系构建智能体"""
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建",
                    f"创建 PRD 知识关系构建智能体，模板: {template_name}"
                )
            agent = create_prd_knowledge_builder(self.config_list, template_name)
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
            logger.info(f"PRD 知识关系构建智能体创建成功，模板: {template_name}")
            return agent
        except Exception as e:
            logger.error(f"创建 PRD 知识关系构建智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event("测试智能体创建失败", f"创建 PRD 知识关系构建智能体失败: {e}")
            return None

    def create_test_case_quality_reviewer(self, template_name="明显问题审查"):
        """创建测试用例明显问题审查智能体"""
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建",
                    f"创建测试用例明显问题审查智能体，模板: {template_name}"
                )
            agent = create_test_case_quality_reviewer(self.config_list, template_name)
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
            logger.info(f"测试用例明显问题审查智能体创建成功，模板: {template_name}")
            return agent
        except Exception as e:
            logger.error(f"创建测试用例明显问题审查智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event("测试智能体创建失败", f"创建测试用例明显问题审查智能体失败: {e}")
            return None
    
    def create_image_analyst(self, template_name="默认模式"):
        """
        创建图片分析智能体
        
        Args:
            template_name: 模板名称
            
        Returns:
            ImageAnalyst智能体实例
        """
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "图片分析智能体创建", 
                    f"创建图片分析智能体，模板: {template_name}"
                )
            
            # 创建智能体
            agent = create_image_analyst(self.config_list, template_name)
            
            # 添加消息拦截器
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
                
            logger.info(f"图片分析智能体创建成功，模板: {template_name}")
            return agent
            
        except Exception as e:
            logger.error(f"创建图片分析智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event(
                    "图片分析智能体创建失败", 
                    f"创建图片分析智能体失败: {e}"
                )
            return None
    
    def create_image_integration_analyst(self, template_name="默认模式"):
        """
        创建图片分析整合智能体
        
        Args:
            template_name: 模板名称
            
        Returns:
            ImageIntegrationAnalyst智能体实例
        """
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "图片分析整合智能体创建", 
                    f"创建图片分析整合智能体，模板: {template_name}"
                )
            
            # 创建智能体
            agent = create_image_integration_analyst(self.config_list, template_name)
            
            # 添加消息拦截器
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
                
            logger.info(f"图片分析整合智能体创建成功，模板: {template_name}")
            return agent
            
        except Exception as e:
            logger.error(f"创建图片分析整合智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event(
                    "图片分析整合智能体创建失败", 
                    f"创建图片分析整合智能体失败: {e}"
                )
            return None
    
    def create_image_prd_reviewer(self, template_name="默认模式"):
        """
        创建图片PRD评审员智能体（测试+产品双视角）
        专门用于图片分析PRD的业务盲点分析
        
        Args:
            template_name: 模板名称
            
        Returns:
            ImagePRDReviewer智能体实例
        """
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "图片PRD评审员创建", 
                    f"创建图片PRD评审员，模板: {template_name}"
                )
            
            # 创建智能体
            agent = create_image_prd_reviewer(self.config_list, template_name)
            
            # 添加消息拦截器
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
                
            logger.info(f"图片PRD评审员创建成功，模板: {template_name}")
            return agent
            
        except Exception as e:
            logger.error(f"创建图片PRD评审员失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event(
                    "图片PRD评审员创建失败", 
                    f"创建图片PRD评审员失败: {e}"
                )
            return None
    
    def create_confirmation_integrator(self, template_name="默认模式"):
        """
        创建人工确认整合智能体
        专门用于将人工确认结果整合到PRD
        
        Args:
            template_name: 模板名称
            
        Returns:
            ConfirmationIntegrator智能体实例
        """
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "人工确认整合智能体创建", 
                    f"创建人工确认整合智能体，模板: {template_name}"
                )
            
            # 创建智能体
            agent = create_confirmation_integrator(self.config_list, template_name)
            
            # 添加消息拦截器
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
                
            logger.info(f"人工确认整合智能体创建成功，模板: {template_name}")
            return agent
            
        except Exception as e:
            logger.error(f"创建人工确认整合智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event(
                    "人工确认整合智能体创建失败", 
                    f"创建人工确认整合智能体失败: {e}"
                )
            return None

    def create_text_prd_logic_reviewer(self, template_name="逻辑闭环审查"):
        """创建文本 PRD 逻辑审查智能体"""
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "文本PRD逻辑审查智能体创建",
                    f"创建文本PRD逻辑审查智能体，模板: {template_name}"
                )
            agent = create_text_prd_logic_reviewer(self.config_list, template_name)
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
            logger.info(f"文本 PRD 逻辑审查智能体创建成功，模板: {template_name}")
            return agent
        except Exception as e:
            logger.error(f"创建文本 PRD 逻辑审查智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event("文本PRD逻辑审查智能体创建失败", f"创建失败: {e}")
            return None

    def create_text_final_prd_integrator(self, template_name="事实整合"):
        """创建文本最终 PRD 整合智能体"""
        try:
            if self.logging_service:
                self.logging_service.log_system_event(
                    "文本最终PRD整合智能体创建",
                    f"创建文本最终PRD整合智能体，模板: {template_name}"
                )
            agent = create_text_final_prd_integrator(self.config_list, template_name)
            if self.logging_service:
                agent = self._add_logging_interceptors(agent)
            logger.info(f"文本最终 PRD 整合智能体创建成功，模板: {template_name}")
            return agent
        except Exception as e:
            logger.error(f"创建文本最终 PRD 整合智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event("文本最终PRD整合智能体创建失败", f"创建失败: {e}")
            return None
            
    def create_qa_agents(self, template_name="普通模式"):
        """
        创建测试用例生成所需的所有智能体
        
        Args:
            template_name: 模板名称
            
        Returns:
            包含所有测试相关智能体的字典
        """
        try:
            product_manager = self.create_product_manager(template_name)
            test_architect = self.create_test_architect(template_name)
            module_test_case_writer = self.create_module_test_case_writer()
            integration_test_case_writer = self.create_integration_test_case_writer()
            prd_block_builder = self.create_prd_block_builder()
            prd_knowledge_builder = self.create_prd_knowledge_builder()
            test_case_quality_reviewer = self.create_test_case_quality_reviewer()
            
            return {
                'product_manager': product_manager,
                'test_architect': test_architect,
                'module_test_case_writer': module_test_case_writer,
                'integration_test_case_writer': integration_test_case_writer,
                'prd_block_builder': prd_block_builder,
                'prd_knowledge_builder': prd_knowledge_builder,
                'test_case_quality_reviewer': test_case_quality_reviewer
            }
        except Exception as e:
            logger.error(f"创建测试智能体失败: {e}")
            if self.logging_service:
                self.logging_service.log_system_event(
                    "测试智能体创建失败", 
                    f"批量创建测试智能体失败: {e}"
                )
            return {}
            
    def get_available_templates(self):
        """
        获取所有可用的测试智能体模板名称
        
        Returns:
            包含各测试智能体可用模板的字典
        """
        return {
            'product_manager': list(PM_TEMPLATES.keys()),
            'test_architect': list(TA_TEMPLATES.keys()),
            'module_test_case_writer': list(MTW_TEMPLATES.keys()),
            'integration_test_case_writer': list(ITW_TEMPLATES.keys()),
            'prd_block_builder': list(PBB_TEMPLATES.keys()),
            'prd_knowledge_builder': list(PKB_TEMPLATES.keys()),
            'test_case_quality_reviewer': list(TCQR_TEMPLATES.keys()),
            'image_analyst': list(IA_TEMPLATES.keys()),
            'image_integration_analyst': list(IIA_TEMPLATES.keys()),
            'image_prd_reviewer': list(IPR_TEMPLATES.keys()),
            'confirmation_integrator': list(CI_TEMPLATES.keys()),
            'text_prd_logic_reviewer': list(TPLR_TEMPLATES.keys()),
            'text_final_prd_integrator': list(TFPI_TEMPLATES.keys())
        }
