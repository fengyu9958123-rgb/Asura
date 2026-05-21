"""
人工确认整合Agent模板定义
专门用于将人工确认的答案整合到原始PRD中，生成最终完整的PRD文档
"""

import autogen
import logging

from ..model_selector import get_models_by_type, get_selected_model_config

logger = logging.getLogger(__name__)


# 人工确认整合Agent模板
TEMPLATES = {
    "默认模式": {
        "temperature": 0.2,  # 更低的温度，确保精确整合
        "system_message": """
# 角色

你是人工确认整合专员，负责把人工确认答案整合回原始 PRD，生成最终完整 PRD。

# 核心原则

1. 忠实整合：只整合人工确认答案中明确的信息，不擅自新增、扩展或优化。
2. 保留原文：不得删除、弱化、改写或调整原 PRD 已有业务内容和结构；只在合适位置补充确认信息。
3. 精确保留：数值、规则、流程、状态、字段、提示文案等关键信息必须按确认答案保留。
4. 自然融合：确认答案应转化为正式 PRD 表述，放在对应功能、规则或异常说明附近，格式和术语与原文一致。

# 整合要求

- 先根据问题标题、关联功能、问题说明和确认结论定位到 PRD 中最相关的位置。
- 如果原 PRD 已有相关描述，在原描述附近补充；如果完全未提及，在最合适章节新增段落或条目。
- 如果确认答案是“选项1/选项2”等短值，必须结合输入中的“已解析确认结论”或候选选项理解其真实含义。
- 只允许整合“已解析确认结论”中明确给出的内容；候选选项、参考示例、原 PRD 中未确认的 `<HUMAN_CONFIRM_*>` 待确认问题不得当成需求正文。
- 整合后不得保留“待确认问题”“人工确认问题”等待处理章节或标签。
- 输出必须是最终完整 PRD 文档，不要省略，不要只输出 diff。

# 禁止事项

- 不得把确认问题原样贴到正文。
- 不得新增人工确认和原 PRD 都没有声明的角色、页面、按钮、字段、状态、异常、时间阈值、规则或能力。
- 不得从待确认问题的参考示例中挑选答案；没有用户确认答案的问题必须从最终 PRD 删除或保持原 PRD 已有的不确定表述。
- 不得输出与 PRD 无关的分析过程。

# 输出

先输出最终完整 PRD。若需要说明整合情况，可在 PRD 后追加简短“整合清单”；系统会自动清理非 PRD 报告。
        """
    }
}


def create_confirmation_integrator(config_list, template_name="默认模式"):
    """
    创建人工确认整合Agent
    
    Args:
        config_list: LLM配置列表
        template_name: 模板名称，默认"默认模式"
    
    Returns:
        autogen.AssistantAgent: 配置好的人工确认整合Agent
    """
    if template_name not in TEMPLATES:
        logger.warning(f"模板 '{template_name}' 不存在，使用默认模式")
        template_name = "默认模式"
    
    template = TEMPLATES[template_name]
    
    logger.info(f"创建人工确认整合Agent，模板：{template_name}")
    
    # 使用文本模型（默认）
    text_config = get_models_by_type(config_list, model_type="requirement")
    
    integrator = autogen.AssistantAgent(
        name="ConfirmationIntegrator",
        system_message=template["system_message"],
        llm_config={
            "config_list": text_config,
            "temperature": template["temperature"],
            "timeout": 300,
        }
    )
    integrator.billing_config = get_selected_model_config(config_list, model_type="requirement")
    
    logger.info(f"✅ 人工确认整合Agent创建成功")
    
    return integrator
