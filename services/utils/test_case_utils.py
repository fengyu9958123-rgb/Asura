"""
测试用例工具模块
负责测试用例的提取和处理
"""

import logging
import re

logger = logging.getLogger(__name__)

def extract_test_cases_from_markdown(file_service, markdown_content):
    """从Markdown内容中提取测试用例"""
    try:
        # 使用file_service中的方法解析表格
        df = file_service.parse_test_cases_from_markdown(markdown_content)
        
        if df is None or len(df) == 0:
            logger.warning("未能从Markdown中提取到测试用例")
            return []
        
        # 转换为字典列表
        test_cases = df.to_dict('records')
        logger.info(f"从Markdown中提取了 {len(test_cases)} 条测试用例")
        return test_cases
    except Exception as e:
        logger.error(f"提取测试用例失败: {e}")
        return [] 