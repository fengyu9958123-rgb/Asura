"""
确认项目工具模块
负责处理人工确认项目的提取和解析
"""

import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def calculate_similarity(text1, text2):
    """计算两个文本的相似度"""
    if not text1 or not text2:
        return 0.0

    # 使用SequenceMatcher计算相似度
    return SequenceMatcher(None, text1.strip(), text2.strip()).ratio()


def is_duplicate_item(new_item, existing_items, threshold=0.95):
    """检查新项目是否与已存在项目重复"""
    new_title = new_item.get('question', '')
    new_content = new_item.get('question_details', '')
    new_combined = f"{new_title}\n{new_content}"

    for existing_item in existing_items:
        existing_title = existing_item.get('question', '')
        existing_content = existing_item.get('question_details', '')
        existing_combined = f"{existing_title}\n{existing_content}"

        # 计算标题+内容的整体相似度
        similarity = calculate_similarity(new_combined, existing_combined)

        if similarity >= threshold:
            logger.info(f"发现重复项目，相似度: {similarity:.2%}")
            return True

    return False


def extract_confirmation_items(content):
    """从内容中提取人工确认项目"""
    intervention_items = []

    try:
        # 如果内容为空，直接返回
        if not content:
            return []

        # 使用字符串分割而不是正则表达式，统一标签格式
        start_tag = '<HUMAN_CONFIRM_START>'
        end_tag = '<HUMAN_CONFIRM_END>'

        parts = content.split(start_tag)
        matches = []

        # 跳过第一部分（开始标记之前的内容）
        for part in parts[1:]:
            if end_tag in part:
                confirm_content = part.split(end_tag)[0]
                matches.append(confirm_content)

        logger.info(f"从内容中提取到 {len(matches)} 个原始确认项目")

        # 处理每个匹配项
        for i, match in enumerate(matches):
            section = match.strip()
            if not section:
                continue

            # 检查项目有效性
            if is_valid_confirmation_item(section):
                # 解析项目
                item_data = parse_confirmation_item(section, i+1)
                if item_data:
                    # 检查是否与已有项目重复
                    if not is_duplicate_item(item_data, intervention_items):
                        intervention_items.append(item_data)
                        question = item_data.get('question', '未知')[:50]
                        logger.info(f"添加新确认项目: {question}")
                    else:
                        question = item_data.get('question', '未知')[:50]
                        logger.info(f"跳过重复项目: {question}")

        # 记录有效项目
        logger.info(f"过滤后剩余 {len(intervention_items)} 个有效确认项目")

        return intervention_items

    except Exception as e:
        logger.error(f"提取确认项目失败: {e}")
        logger.exception("详细错误信息")
        return []


def is_valid_confirmation_item(item):
    """检查确认项目是否有效"""
    if not item or len(item.strip()) < 10:
        return False

    # 宽松检查：只要内容有一定长度且包含标题或确认点即可
    has_title = '问题标题:' in item
    has_confirm_points = '确认点:' in item

    # 只要有标题或确认点中的任一个即可
    if not (has_title or has_confirm_points):
        return False

    # 检查是否有实际文字内容（排除只有标记的情况）
    content_lines = [line.strip() for line in item.split('\n') if line.strip()]
    meaningful_content = []

    for line in content_lines:
        # 排除只是标记行的内容
        markers = ['问题标题:', '确认点:', '问题描述:']
        if not any(marker in line for marker in markers):
            meaningful_content.append(line)

    # 至少要有一些有意义的内容
    return (len(meaningful_content) > 0 and
            len('\n'.join(meaningful_content)) > 15)


def parse_confirmation_item(item, item_id):
    """解析确认项目为结构化数据"""
    lines = item.split('\n')

    # 提取标题
    title = ""
    description = []
    confirm_points = []
    all_content = []

    section = "none"

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if '问题标题:' in line:
            title = line.split('问题标题:')[1].strip()
            section = "description"
        elif '问题描述:' in line:
            section = "description"
        elif '确认点:' in line:
            section = "confirm"
        elif section == "description" and line:
            description.append(line)
            all_content.append(line)
        elif section == "confirm" and line:
            # 宽松提取：所有内容都保存，同时尝试提取数字开头的选项
            all_content.append(line)
            if any(line.startswith(f'{num}.') for num in range(1, 10)):
                content = (line.split('.', 1)[1].strip()
                           if '.' in line else line)
                if content:
                    confirm_points.append(content)
            else:
                # 即使不是数字开头，也作为确认点内容保存
                confirm_points.append(line)
        else:
            # 其他内容也保存到all_content中
            all_content.append(line)

    # 如果没有提取到标题，尝试从内容第一行获取
    if not title and all_content:
        first_line = all_content[0]
        title = (first_line[:50] + "..." if len(first_line) > 50
                 else first_line)

    # 如果没有确认点，将所有内容作为确认点
    if not confirm_points and all_content:
        confirm_points = all_content

    # 宽松检查：只要有内容就返回结构化数据
    if not title and not confirm_points:
        return None

    # 构建结构化数据，与generation_service期望的格式兼容
    desc = ('\n'.join(description) if description
            else '\n'.join(all_content[:3]))

    item_data = {
        'id': f'human_confirm_{item_id}',
        'question_details': item,  # 保存原始内容用于去重
        'user_answer': '',
        # 保留原有字段用于向后兼容
        'question': title or "未知问题",
        'description': desc,
        'confirm_points': confirm_points,
        'options': ['是', '否', '需要更多信息']  # 默认选项
    }

    return item_data


def generate_confirmation_summary(confirmation_results):
    """生成人工确认摘要"""
    summary = "## 人工确认结果\n\n"

    for i, item in enumerate(confirmation_results):
        question_details = item.get('question_details', '未知问题详情')
        user_answer = item.get('user_answer', '未提供')

        summary += f"### 确认项 {i+1}\n\n"
        summary += f"**问题详情:**\n{question_details}\n\n"
        summary += f"**用户回答:** {user_answer}\n\n"
        summary += "---\n\n"

    # summary += "请根据以上人工确认的结果完善PRD文档。"

    return summary

