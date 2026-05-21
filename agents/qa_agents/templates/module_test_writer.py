"""
ModuleTestCaseWriter Agent template.
"""

import autogen

from ..model_selector import get_models_by_type, get_selected_model_config
from .test_case_writer_common import (
    COMMON_FACT_RULES,
    COMMON_OUTPUT_RULES,
    NORMAL_DUPLICATE_RULES,
    NORMAL_PRIORITY_RULES,
    NORMAL_BEHAVIOR_RULES,
)


SYSTEM_MESSAGE = f"""# 角色

你是资深测试用例编写工程师。你的任务是基于当前 normal_lu 的用例生成上下文，生成覆盖完整、可执行、可断言的测试用例。

# 普通 LU 输入理解

- 当前单元类型只应是 `normal_lu`。
- “当前 LU 主需求 BLOCK”是本次必须完整覆盖的内容。
- 主需求 BLOCK 中明确写到的功能、规则、字段、状态、异常、边界、文案和用户可见结果，都必须有用例显式断言。
- 不要为其他 LU 生成独立用例。

{COMMON_FACT_RULES}

{NORMAL_BEHAVIOR_RULES}

{NORMAL_DUPLICATE_RULES}

{NORMAL_PRIORITY_RULES}

{COMMON_OUTPUT_RULES}
"""

TEMPLATES = {
    "模块包生成": {
        "temperature": 0.3,
        "system_message": SYSTEM_MESSAGE,
    }
}


def create_module_test_case_writer(config_list, template_name="模块包生成"):
    template = TEMPLATES.get(template_name, TEMPLATES["模块包生成"])
    text_config = get_models_by_type(config_list, model_type="testcase")

    agent = autogen.AssistantAgent(
        name="ModuleTestCaseWriter",
        system_message=template["system_message"],
        llm_config={
            "config_list": text_config,
            "temperature": template["temperature"],
            "timeout": 600,
        },
    )
    agent.billing_config = get_selected_model_config(config_list, model_type="testcase")
    return agent
