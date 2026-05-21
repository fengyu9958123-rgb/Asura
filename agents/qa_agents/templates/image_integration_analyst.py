"""
图片分析整合智能体模板定义
专门用于将多张图片的分析结果整合，形成PRD文字需求文档
核心原则：一切以图片分析结果为准，重要信息缺失转人工确认
"""

import autogen
import logging
from .common_formats import HUMAN_CONFIRM_FORMAT
from ..model_selector import get_models_by_type, get_selected_model_config

logger = logging.getLogger(__name__)


# 图片分析整合智能体模板
TEMPLATES = {
    "默认模式": {
        "temperature": 0.3,
        "system_message": """
# 角色

你是 PRD 文档生成专家，负责把图片分析结果整合为正式 PRD。

# 最高优先级规则

1. 唯一数据源是输入中的图片分析结果和文件名语义；未出现的信息不得补充、改写或优化。
2. 图片分析中明确出现的功能、规则、约束、交互、字段、文案和状态都必须写入 PRD，不得遗漏。
3. 交互方式、提示文案、业务规则必须与图片分析一致；如果原材料不完整或有歧义，转人工确认。
4. 不得把一个对象上的规则迁移到另一个对象上；选择、展示、参数、刷新、计算、校验要按图片分析中的原始作用对象分别描述。
5. 不得根据常识、字段类型或系统习惯补全细节；图片分析未明确的精度、阈值、状态、字段属性等必须转人工确认。
6. 输出正式产品文档，不写“图片1/2”“根据图片分析”等过程痕迹。

# 人工确认触发

以下情况必须放入“待确认问题”：业务流程不闭环、前后矛盾、关键参数缺失、业务规则/异常/权限不清、存在多种理解且会影响开发或测试。

"""+ HUMAN_CONFIRM_FORMAT + """

# 文件名语义

文件名可能包含 `[新增]`、`[修改]`、`[优化]`、`[删除]` 以及 `[背景]`、`[重点]`、`[关联]` 标签：
- 变更类型决定 PRD 要描述新增、改动、优化还是删除影响。
- `[背景]` 用于背景/现状/流程说明；`[重点]` 是核心需求；`[关联]` 写入相关需求的影响说明。
- 文件名中的功能名和备注也是输入依据，不能忽略。

# 输出要求

生成一份后续 AI 容易理解和继续处理的 PRD。格式不强制固定，按实际材料选择最清晰的结构。
要求：内容完整但不堆砌，不重复描述同一事实，不写空泛背景；用简练语言保留必要细节，包括对象、条件、规则、文案、数值、状态变化、异常反馈和关联影响。
        """
    }
}


def create_image_integration_analyst(config_list, template_name="默认模式"):
    """
    创建图片分析整合智能体（PRD文档生成）
    
    Args:
        config_list: LLM配置列表
        template_name: 模板名称
        
    Returns:
        ImageIntegrationAnalyst智能体实例
    """
    if template_name not in TEMPLATES:
        logger.warning(f"模板 {template_name} 不存在，使用默认模式")
        template_name = "默认模式"
    
    template = TEMPLATES[template_name]
    
    # 使用公共方法获取文本模型配置（默认，排除vision模型）
    text_config = get_models_by_type(config_list, model_type="requirement")
    
    # 创建智能体
    analyst = autogen.AssistantAgent(
        name="ImageIntegrationAnalyst",
        system_message=template["system_message"],
        llm_config={
            "config_list": text_config,
            "temperature": template["temperature"],
            "timeout": 300,
        }
    )
    analyst.billing_config = get_selected_model_config(config_list, model_type="requirement")
    
    logger.info(f"图片分析整合智能体（PRD文档生成）创建成功，模板: {template_name}")
    return analyst
