"""
智能体工厂统一入口模块
提供对所有智能体的统一访问接口，兼容原有代码
"""

import logging
from .qa_agents.factory import QAAgentFactory

logger = logging.getLogger(__name__)


class AgentFactory:
    """
    智能体工厂统一入口类，兼容原有代码
    
    注意：此类为兼容性保留，新代码建议直接使用：
    - QAAgentFactory: 用于测试用例生成相关agents
    """
    
    def __init__(self, config_list=None, logging_service=None):
        """
        初始化统一工厂
        
        Args:
            config_list: LLM配置列表
            logging_service: 日志服务实例
        """
        self.config_list = config_list
        self.logging_service = logging_service
        
        # 初始化子工厂
        self.qa_factory = QAAgentFactory(config_list, logging_service)
    
    # =============== 兼容性方法：测试用例生成相关 ===============
        
    def create_product_manager(self, template_name="普通模式"):
        """创建产品经理智能体（兼容性方法，委托给QAAgentFactory）"""
        return self.qa_factory.create_product_manager(template_name)
            
    def create_test_architect(self, template_name="普通模式"):
        """创建测试架构师智能体（兼容性方法，委托给QAAgentFactory）"""
        return self.qa_factory.create_test_architect(template_name)
            
    def create_module_test_case_writer(self, template_name="模块包生成"):
        """创建模块测试用例编写智能体（兼容性方法，委托给QAAgentFactory）"""
        return self.qa_factory.create_module_test_case_writer(template_name)

    def create_integration_test_case_writer(self, template_name="链路包生成"):
        """创建链路测试用例编写智能体（兼容性方法，委托给QAAgentFactory）"""
        return self.qa_factory.create_integration_test_case_writer(template_name)

    def create_prd_block_builder(self, template_name="PRD分块"):
        """创建 PRD 分块智能体（兼容性方法，委托给QAAgentFactory）"""
        return self.qa_factory.create_prd_block_builder(template_name)

    def create_prd_knowledge_builder(self, template_name="知识关系构建"):
        """创建 PRD 知识关系构建智能体（兼容性方法，委托给QAAgentFactory）"""
        return self.qa_factory.create_prd_knowledge_builder(template_name)

    def create_test_case_quality_reviewer(self, template_name="明显问题审查"):
        """创建测试用例明显问题审查智能体（兼容性方法，委托给QAAgentFactory）"""
        return self.qa_factory.create_test_case_quality_reviewer(template_name)
    
    def create_all_agents(self, template_name="普通模式"):
        """
        创建所有测试相关的智能体（兼容性方法，委托给QAAgentFactory）
        
        Args:
            template_name: 模板名称
            
        Returns:
            包含所有智能体的字典
        """
        return self.qa_factory.create_qa_agents(template_name)

    # =============== 工厂管理方法 ===============
            
    def get_available_templates(self):
        """
        获取所有可用的模板名称
        
        Returns:
            包含各智能体可用模板的字典
        """
        return self.qa_factory.get_available_templates()

    def get_qa_factory(self):
        """获取测试用例生成工厂实例"""
        return self.qa_factory
