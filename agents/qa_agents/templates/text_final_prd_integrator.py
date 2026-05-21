"""Text final PRD integration agent template."""

import autogen
import logging

from ..model_selector import get_models_by_type, get_selected_model_config

logger = logging.getLogger(__name__)


TEMPLATES = {
    "事实整合": {
        "temperature": 0.2,
        "system_message": """
# 角色

你是最终 PRD 整合专员。你的任务是把“原始 PRD”和“人工确认结果”整合为一份结构清晰、便于后续需求拆分和测试用例生成理解的最终 PRD。

# 最高原则

- 最终 PRD 的所有需求事实只能来自原始 PRD和人工确认结果。
- 允许调整语言、标题、层级和顺序，让文档更清晰。
- 允许把分散在原文不同位置但属于同一业务点的事实合并描述。
- 不得新增、推测、扩展、改写任何未被原始 PRD 或人工确认明确支持的业务事实。
- 不得删除、弱化、遗漏原始 PRD 中已有的需求事实。
- 人工确认结果高于原始 PRD 中的不确定表述，但不得影响无关需求。

# 整合规则

1. 先完整保留原始 PRD 的功能、规则、流程、字段、页面、状态、异常和约束。
2. 再把人工确认答案转成正式需求描述，放入最相关章节。
3. 如果人工确认回答的是开放文本，按其明确语义整合，不要继续发散。
4. 如果原文存在待确认、疑问、未定等表达，且人工已确认，则替换为明确结论。
5. 如果没有人工确认项，也需要基于原文整理为最终 PRD，但不能增加新事实。
6. 最终文档要方便后续 Agent 使用：标题清晰、功能边界清楚、规则可测试、链路顺序明确。

# 禁止事项

- 不要输出“优化建议”“设计建议”“可考虑”等非需求内容。
- 不要保留人工确认问题原文、选项列表、审查过程或分析过程。
- 不要添加技术实现方案、接口、数据库、性能指标、架构方案。
- 不要为了完整性补齐原文没有的默认规则。

# 输出格式

只输出最终 PRD Markdown 正文，不要包裹 JSON，不要输出解释。
        """,
    }
}


def create_text_final_prd_integrator(config_list, template_name="事实整合"):
    if template_name not in TEMPLATES:
        logger.warning(f"模板 '{template_name}' 不存在，使用默认模板")
        template_name = "事实整合"

    template = TEMPLATES[template_name]
    text_config = get_models_by_type(config_list, model_type="requirement")
    agent = autogen.AssistantAgent(
        name="TextFinalPRDIntegrator",
        system_message=template["system_message"],
        llm_config={
            "config_list": text_config,
            "temperature": template["temperature"],
            "timeout": 300,
        },
    )
    agent.billing_config = get_selected_model_config(config_list, model_type="requirement")
    logger.info("✅ 文本最终 PRD 整合 Agent 创建成功")
    return agent
