#!/usr/bin/env python3
"""
图片需求 → 测试用例生成 - 核心AI逻辑
只包含纯AI调用逻辑，不包含流程控制
供生产环境(image_pipeline_service.py)和测试脚本(scripts/)共享使用
"""

import os
import json
import base64
import re
import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

# 确保项目路径
import sys
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.utils.notes_manager import NotesManager, extract_note_from_filename
from services.generation.prd_document_cleaner import align_playback_speeds_to_sources, clean_prd_document
from services.generation.llm_response_cleaner import strip_model_reasoning
from services.generation.llm_usage import record_current_agent_call
from services.generation.structured_testcase_pipeline import StructuredTestcasePipeline

logger = logging.getLogger(__name__)


# ============================================================================
# 辅助函数
# ============================================================================

def image_to_base64(image_path):
    """将图片转换为Base64编码"""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def extract_confirmation_items(text):
    """
    从PRD审核结果中提取确认项清单
    支持三种格式：
    1. 新的开放式格式（带问题说明和参考示例）
    2. 旧的选项式格式（带确认点列表）
    3. 原始Q/P编号格式

    Returns:
        List[Dict]: 确认项列表，每项包含 number, title, description, options/examples, raw_text
    """
    items = []

    def split_tagged_blocks(content: str) -> List[str]:
        """提取人工确认块，容忍缺失结束标签的情况。"""
        start_tag = '<HUMAN_CONFIRM_START>'
        end_tag = '<HUMAN_CONFIRM_END>'
        blocks: List[str] = []
        pos = 0

        while True:
            start = content.find(start_tag, pos)
            if start == -1:
                break

            body_start = start + len(start_tag)
            next_end = content.find(end_tag, body_start)
            next_start = content.find(start_tag, body_start)

            if next_end != -1 and (next_start == -1 or next_end < next_start):
                body_end = next_end
                pos = next_end + len(end_tag)
            elif next_start != -1:
                # 当前块缺失结束标签，以下一个开始标签作为当前块结束位置
                body_end = next_start
                pos = next_start
            else:
                body_end = len(content)
                pos = len(content)

            block = content[body_start:body_end].strip()
            if block:
                blocks.append(block)

        return blocks

    # 首先尝试提取带标签的格式
    tagged_matches = split_tagged_blocks(text)

    if tagged_matches:
        # 解析带标签的格式
        for block in tagged_matches:
            try:
                # 提取各字段
                number_match = re.search(r'问题编号[:：]\s*([PQ]\d+-?\d{3})', block)
                title_match = re.search(r'(?:问题标题|问题)[:：]\s*(.*?)(?=\n|$)', block)

                number = number_match.group(1).strip() if number_match else ""
                title = title_match.group(1).strip() if title_match else '未提供标题'

                # 尝试新格式：问题/描述 + 参考示例（兼容旧的关联功能 + 问题说明）
                related_func_match = re.search(r'关联功能[:：]\s*(.*?)(?=\n|$)', block)
                desc_match_new = re.search(r'(?:问题说明|问题描述|描述)[:：]\s*(.*?)(?=\n参考示例|$)', block, re.DOTALL)
                examples_match = re.search(r'参考示例[:：]?\s*\n(.*?)(?=\n(?:【|<)|$)', block, re.DOTALL)

                if desc_match_new and examples_match:
                    # 新的开放式格式
                    related_function = related_func_match.group(1).strip() if related_func_match else ""
                    description = desc_match_new.group(1).strip()
                    examples_text = examples_match.group(1).strip()

                    # 提取示例列表
                    options = []
                    for line in examples_text.split('\n'):
                        line = line.strip()
                        if line and line.startswith('-'):
                            example = re.sub(r'^-\s*', '', line)
                            if example and not example.startswith('<'):
                                options.append(example.strip())

                    items.append({
                        'number': number,
                        'title': title,
                        'related_function': related_function,  # 关联的功能点
                        'description': description,
                        'options': options,  # 这里存的是示例，但字段名保持options以兼容前端
                        'format_type': 'open',  # 标记为开放式格式
                        'raw_text': block.strip()
                    })
                else:
                    # 尝试旧格式：确认点
                    desc_match_old = re.search(r'问题描述[:：]\s*(.*?)(?=\n确认点|$)', block, re.DOTALL)
                    confirm_section_match = re.search(r'确认点[:：]?\s*\n(.*?)(?=\n(?:【|<)|$)', block, re.DOTALL)

                    description = desc_match_old.group(1).strip() if desc_match_old else '未提供描述'
                    options = []

                    if confirm_section_match:
                        confirm_text = confirm_section_match.group(1).strip()
                        for line in confirm_text.split('\n'):
                            line = line.strip()
                            if line and (line[0].isdigit() or line.startswith('-')):
                                # 清理选项文本
                                option = re.sub(r'^\d+\.\s*', '', line)
                                option = re.sub(r'^-\s*', '', option)
                                if option and not option.startswith('<'):
                                    options.append(option.strip())

                    items.append({
                        'number': number,
                        'title': title,
                        'description': description,
                        'options': options,
                        'format_type': 'choice',  # 标记为选择式格式
                        'raw_text': block.strip()
                    })

            except Exception as e:
                logger.warning(f"解析确认问题块失败: {e}")
                continue
    else:
        # 回退到原格式解析
        # 匹配确认类问题（Q开头）
        q_pattern = r'(Q\d{3})[:：]\s*(.*?)\n确认点[:：]?\s*\n((?:.*?\n)+?)(?=\n(?:Q\d{3}|P\d-\d{3}|$))'

        for match in re.finditer(q_pattern, text, re.DOTALL):
            number = match.group(1).strip()
            title = match.group(2).strip()
            confirm_points_text = match.group(3).strip()

            # 提取确认点（选项）
            options = []
            for line in confirm_points_text.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-')):
                    # 清理选项文本
                    option = re.sub(r'^\d+\.\s*', '', line)
                    option = re.sub(r'^-\s*', '', option)
                    if option:
                        options.append(option.strip())

            items.append({
                'number': number,
                'title': title,
                'description': '未提供描述',  # Q类问题通常没有描述
                'options': options,
                'raw_text': match.group(0).strip()
            })

        # 匹配问题类（P开头）
        p_pattern = r'(P\d-\d{3})[:：]\s*(.*?)\n.*?问题分类[:：]?\s*(.*?)\n.*?问题描述[:：]?\s*(.*?)\n确认点[:：]?\s*\n((?:.*?\n)+?)(?=\n(?:Q\d{3}|P\d-\d{3}|$))'

        for match in re.finditer(p_pattern, text, re.DOTALL):
            number = match.group(1).strip()
            title = match.group(2).strip()
            description = match.group(4).strip()
            confirm_points_text = match.group(5).strip()

            # 提取确认点
            options = []
            for line in confirm_points_text.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-')):
                    option = re.sub(r'^\d+\.\s*', '', line)
                    option = re.sub(r'^-\s*', '', option)
                    if option:
                        options.append(option.strip())

            items.append({
                'number': number,
                'title': title,
                'description': description,
                'options': options,
                'raw_text': match.group(0).strip()
            })

    return items


# ============================================================================
# 核心AI函数 - 从 test_generate_prd_from_images.py 移动
# ============================================================================

def analyze_module_images(image_analyst, module_info, output_dir, notes_mgr=None, conv_logger=None):
    """
    分析模块中的所有图片（一次性批量发送）

    Args:
        image_analyst: ImageAnalyst智能体实例
        module_info: 模块信息字典
        output_dir: 输出目录
        notes_mgr: NotesManager实例（可选）
        conv_logger: ConversationLogger实例（可选）

    Returns:
        Dict: 包含模块信息和图片分析结果
    """
    module_name = module_info['module_name']
    logger.info(f"开始分析模块: {module_name}")

    try:
        # 🆕 预分类所有图片（根据文件名中的标签）
        images_classification = {}
        classification_summary = {'BACKGROUND': 0, 'FOCUS': 0, 'RELATED': 0}

        # 图片类型标签定义
        IMAGE_TYPE_TAGS = {
            '[背景]': 'BACKGROUND',
            '[重点]': 'FOCUS',
            '[关联]': 'RELATED'
        }

        for img_info in module_info['images']:
            # 优先使用 original_name，如果为空则使用 filename，最后降级到 name
            filename = img_info.get('original_name') or img_info.get('filename') or img_info.get('name', '')
            logger.debug(f"🔍 处理图片: filename={filename}, img_info keys={list(img_info.keys())}")

            # 从文件名提取图片类型标签
            img_type = 'FOCUS'  # 默认为重点
            for tag, type_code in IMAGE_TYPE_TAGS.items():
                if tag in filename:
                    img_type = type_code
                    logger.debug(f"  ✅ 匹配到标签: {tag} -> {type_code}")
                    break

            # 使用文件名作为唯一标识（因为 module_info['images'] 中没有 id 字段）
            img_id = img_info.get('id') or img_info.get('name') or filename
            images_classification[img_id] = {
                'type': img_type,
                'filename': filename
            }
            classification_summary[img_type] += 1
            logger.debug(f"  📊 img_id={img_id}, 分类: {img_type}, 累计统计: {classification_summary}")

        logger.info(f"📊 图片分类统计: {classification_summary}")

        # 继续原有的图片分析流程...
        # 构建提示词（图片分析阶段不需要需求文档补充，保持纯粹的图片分析）
        prompt = f"""你是资深产品经理，负责分析产品需求图片。

【当前模块】{module_name}
【图片总数】{len(module_info['images'])} 张

【图片详情】
"""

        # 逐张图片添加（带文件名备注）
        for i, img_info in enumerate(module_info['images'], 1):
            # 从文件名提取备注
            img_note = extract_note_from_filename(img_info['filename'])

            prompt += f"\n图片 {i}: {img_info['filename']}\n"
            prompt += f"变更类型: {img_info['change_type']}\n"
            if img_note:
                prompt += f"📌 备注: {img_note}\n"

        prompt += """

【分析任务】
请逐张详细分析每个图片，提取需求信息。

重点关注：
1. 视觉标注（红框、箭头、文字备注等）
2. 交互细节（联动、反馈、状态变化）
3. 变更类型（新增/修改/删除/优化）
4. 如果图片有人工备注，优先关注备注内容

最后进行模块级整合分析，形成完整的交互逻辑描述。
"""

        # 构建多图片内容
        content = [{"type": "text", "text": prompt}]

        for img_info in module_info['images']:
            logger.info(f"正在加载图片: {img_info['filename']}")
            image_base64 = image_to_base64(img_info['path'])
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            })

        # 调用ImageAnalyst
        logger.info(f"调用ImageAnalyst进行批量分析...")
        messages = [{"role": "user", "content": content}]

        before_usage = StructuredTestcasePipeline._agent_usage_snapshot(image_analyst)
        image_analysis = strip_model_reasoning(image_analyst.generate_reply(messages=messages))
        usage = StructuredTestcasePipeline._agent_usage_delta(image_analyst, before_usage)
        record_current_agent_call(
            agent=image_analyst,
            prompt=prompt,
            response=image_analysis,
            usage=usage,
            estimated=usage is None,
            metadata={"image_count": len(module_info.get("images") or [])},
        )

        logger.info(f"图片分析完成，结果长度: {len(image_analysis)} 字符")

        # 保存分析结果
        analysis_dir = os.path.join(output_dir, 'logs', 'image_analysis')
        os.makedirs(analysis_dir, exist_ok=True)

        module_name_sanitized = re.sub(r'[^\w\s-]', '', module_name).strip()
        analysis_file = os.path.join(analysis_dir, f"{module_name_sanitized}.md")

        with open(analysis_file, 'w', encoding='utf-8') as f:
            f.write(f"# {module_name} - 图片分析结果\n\n{image_analysis}")

        logger.info(f"✅ 图片分析结果已保存: {analysis_file}")

        return {
            'module_info': module_info,
            'image_analysis': image_analysis,
            'analysis_file': analysis_file,
            'prompt': prompt,  # 🆕 返回完整的Prompt
            'images_classification': images_classification,      # 🆕 图片分类信息
            'classification_summary': classification_summary,    # 🆕 分类统计
            'success': True
        }

    except Exception as e:
        logger.error(f"分析模块失败 {module_name}: {e}", exc_info=True)
        return {
            'module_info': module_info,
            'image_analysis': f"❌ 分析失败: {str(e)}",
            'success': False,
            'error': str(e)
        }


def generate_version_prd(prd_generator, version_name, modules_results, output_dir, notes_mgr=None, conv_logger=None):
    """
    生成完整的版本PRD文档

    Args:
        prd_generator: ImageIntegrationAnalyst智能体实例
        version_name: 版本名称
        modules_results: 所有模块的分析结果列表
        output_dir: 输出目录
        notes_mgr: NotesManager实例（可选）
        conv_logger: ConversationLogger实例（可选）

    Returns:
        str: 生成的PRD文档路径
    """
    logger.info("=" * 60)
    logger.info("开始版本级整合...")
    logger.info(f"版本名称: {version_name}")

    # 收集所有成功模块的图片分析结果
    successful_modules = [r for r in modules_results if r.get('success', False)]

    if not successful_modules:
        logger.error("没有成功的模块分析结果，跳过版本级整合")
        return None

    logger.info(f"收集到 {len(successful_modules)} 个成功的模块分析结果")

    # 获取需求文档补充备注
    doc_notes = ""
    if notes_mgr and notes_mgr.has_notes():
        doc_notes = notes_mgr.get_notes_for_stage("需求文档补充")

    # 构建版本级整合提示词
    version_prd_prompt = f"""你是资深产品经理，负责将UI界面图片的分析结果整合提炼，编写完整的产品需求文档（PRD）。

"""

    # 添加备注（如果有）
    if doc_notes:
        version_prd_prompt += f"""【项目背景和需求补充】
{doc_notes}

"""

    # 🆕 收集所有模块的分类统计
    total_classification = {'BACKGROUND': 0, 'FOCUS': 0, 'RELATED': 0}
    for result in successful_modules:
        summary = result.get('classification_summary', {})
        logger.debug(f"🔍 模块 '{result['module_info']['module_name']}' 的分类统计: {summary}")
        for type_code, count in summary.items():
            total_classification[type_code] += count

    logger.info(f"📊 版本级图片分类汇总: {total_classification}")

    version_prd_prompt += f"""版本信息:
- 版本名称: {version_name}
- 功能模块数: {len(successful_modules)} 个
- 图片总数: {sum(len(r['module_info']['images']) for r in successful_modules)} 张

"""

    # 🆕 添加图片清单（按内容分类，再按需求类型细分）
    if total_classification['BACKGROUND'] > 0 or total_classification['FOCUS'] > 0:
        version_prd_prompt += f"""
图片分类 ({sum(total_classification.values())}张)

"""

        # 简化：只按内容分类收集图片列表（不再细分需求类型）
        images_by_content = {
            'BACKGROUND': [],
            'FOCUS': [],
            'RELATED': []
        }

        # 遍历所有成功模块的图片分类信息
        for module_result in successful_modules:
            images_classification = module_result.get('images_classification', {})

            # images_classification 是字典: {img_id: {type, filename}}
            for img_id, img_class in images_classification.items():
                img_name = img_class['filename']
                img_type = img_class['type']  # BACKGROUND, FOCUS, RELATED

                # 按内容分类分组（不需要需求类型，因为每个图片分析里已有）
                images_by_content[img_type].append(img_name)

        logger.info(f"📊 图片清单分组完成: {images_by_content}")

        # 按内容分类输出（背景 -> 重点 -> 关联）
        content_types = [
            ('BACKGROUND', '背景类', total_classification['BACKGROUND']),
            ('FOCUS', '重点类', total_classification['FOCUS']),
            ('RELATED', '关联类', total_classification['RELATED'])
        ]

        for content_code, content_label, count in content_types:
            if count > 0:
                version_prd_prompt += f"""{content_label} ({count}张):
"""
                # 直接列出该分类下的所有图片（不再按需求类型细分）
                images = images_by_content[content_code]
                for img_name in images:
                    version_prd_prompt += f"- {img_name}\n"
                version_prd_prompt += "\n"

    version_prd_prompt += """---

各图片分析结果:

"""

    # 添加每个模块的图片分析结果
    for i, result in enumerate(successful_modules, 1):
        module_info = result['module_info']
        module_name = module_info['module_name']
        image_analysis = result['image_analysis']
        images_list = module_info['images']

        version_prd_prompt += f"""
## 模块 {i:02d}：{module_name}

**包含图片**：{len(images_list)} 张
"""
        # 列出具体图片名称
        for idx, img in enumerate(images_list, 1):
            version_prd_prompt += f"  {idx}. {img['filename']}\n"

        version_prd_prompt += f"""
**分析内容**：
{image_analysis}

---

"""

    # 添加简单的任务指令
    if doc_notes:
        version_prd_prompt += """
【特别说明】
请参考上述【项目背景和需求补充】中的需求目录和文档结构建议。

"""

    version_prd_prompt += """
---

请基于以上图片分析结果，生成完整的版本PRD文档。
"""

    logger.info(f"调用ImageIntegrationAnalyst生成版本级PRD，输入长度: {len(version_prd_prompt)} 字符")

    try:
        # 保存AI输入（prompt）
        logs_dir = os.path.join(output_dir, 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        ai_prompt_file = os.path.join(logs_dir, "ai_prompt.md")
        with open(ai_prompt_file, 'w', encoding='utf-8') as f:
            f.write(f"# 版本级整合 - AI输入Prompt\n\n")
            f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"---\n\n")
            f.write(version_prd_prompt)
        logger.info(f"✅ AI输入prompt已保存: {ai_prompt_file}")

        # 调用AI生成PRD
        messages = [{"role": "user", "content": version_prd_prompt}]
        before_usage = StructuredTestcasePipeline._agent_usage_snapshot(prd_generator)
        version_prd_document = strip_model_reasoning(prd_generator.generate_reply(messages=messages))
        usage = StructuredTestcasePipeline._agent_usage_delta(prd_generator, before_usage)
        record_current_agent_call(
            agent=prd_generator,
            prompt=version_prd_prompt,
            response=version_prd_document,
            usage=usage,
            estimated=usage is None,
        )

        logger.info(f"版本级PRD生成完成，输出长度: {len(version_prd_document)} 字符")

        # 保存AI输出（response）
        ai_response_file = os.path.join(logs_dir, "ai_response.md")
        with open(ai_response_file, 'w', encoding='utf-8') as f:
            f.write(f"# 版本级整合 - AI原始输出\n\n")
            f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"---\n\n")
            f.write(version_prd_document)
        logger.info(f"✅ AI原始输出已保存: {ai_response_file}")

        # 保存最终版本级PRD文档
        prd_dir = os.path.join(output_dir, 'prd')
        os.makedirs(prd_dir, exist_ok=True)
        version_prd_file = os.path.join(prd_dir, "version_prd.md")

        with open(version_prd_file, 'w', encoding='utf-8') as f:
            f.write(f"# {version_name} - 完整需求文档\n\n{version_prd_document}")

        logger.info(f"✅ 版本级PRD文档已保存: {version_prd_file}")

        # 🆕 返回包含Prompt的完整结果
        return {
            'prd_file': version_prd_file,
            'prd_content': version_prd_document,
            'prompt': version_prd_prompt,  # 🆕 返回完整Prompt
            'success': True
        }

    except Exception as e:
        logger.error(f"版本级PRD生成失败: {e}", exc_info=True)
        return None


# ============================================================================
# 核心AI函数 - 从 test_image_prd_complete.py 移动
# ============================================================================

def extract_agent_response(chat_result, agent_name: str) -> str:
    """从autogen的ChatResult中提取指定Agent的响应"""
    response = ""

    if hasattr(chat_result, 'chat_history') and chat_result.chat_history:
        # 从后往前找，获取最后一个来自指定Agent的回复
        for msg in reversed(chat_result.chat_history):
            msg_name = msg.get('name', '')
            msg_role = msg.get('role', '')

            # 匹配条件：name等于agent_name，或者role是assistant且没有name字段
            if msg_name == agent_name or (msg_role == 'assistant' and not msg_name):
                response = msg.get('content', '')
                break

    if not response:
        if hasattr(chat_result, 'summary'):
            response = chat_result.summary
        else:
            response = str(chat_result)

    return str(strip_model_reasoning(response))


def _build_complete_review_result(original_items: List[Dict], new_items: List[Dict]) -> str:
    """构建完整的评审结果（包含原有问题+新增问题），保留标签格式，支持开放式和选择式两种格式"""
    result = "# PRD评审结果\n\n"
    result += "## 原PRD中待确认的问题\n\n"

    if original_items:
        for idx, item in enumerate(original_items, 1):
            result += f"```\n<HUMAN_CONFIRM_START>\n"
            result += f"问题标题: {item.get('title', 'N/A')}\n"

            # 根据format_type决定使用哪种格式
            if item.get('format_type') == 'open':
                # 新的开放式格式：关联功能 + 问题说明 + 参考示例
                if item.get('related_function'):
                    result += f"关联功能: {item.get('related_function')}\n"
                result += f"问题说明: {item.get('description', 'N/A')}\n"
                result += f"参考示例:\n"
                for opt in item.get('options', []):
                    result += f"- {opt}\n"
            else:
                # 旧的选择式格式：问题描述 + 确认点
                if item.get('description') and item.get('description') != '未提供描述':
                    result += f"问题描述: {item.get('description')}\n"
                result += f"确认点:\n"
                for i, opt in enumerate(item.get('options', []), 1):
                    result += f"{i}. {opt}\n"

            result += f"<HUMAN_CONFIRM_END>\n```\n\n"
    else:
        result += "无\n\n"

    result += "## 评审新增的问题\n\n"

    if new_items:
        for idx, item in enumerate(new_items, 1):
            result += f"```\n<HUMAN_CONFIRM_START>\n"
            result += f"问题标题: {item.get('title', 'N/A')}\n"

            # 根据format_type决定使用哪种格式
            if item.get('format_type') == 'open':
                # 新的开放式格式：关联功能 + 问题说明 + 参考示例
                if item.get('related_function'):
                    result += f"关联功能: {item.get('related_function')}\n"
                result += f"问题说明: {item.get('description', 'N/A')}\n"
                result += f"参考示例:\n"
                for opt in item.get('options', []):
                    result += f"- {opt}\n"
            else:
                # 旧的选择式格式：问题描述 + 确认点
                if item.get('description') and item.get('description') != '未提供描述':
                    result += f"问题描述: {item.get('description')}\n"
                result += f"确认点:\n"
                for i, opt in enumerate(item.get('options', []), 1):
                    result += f"{i}. {opt}\n"

            result += f"<HUMAN_CONFIRM_END>\n```\n\n"
    else:
        result += "无\n\n"

    return result


def format_confirmations_with_answers(confirmation_items: List[Dict], answers: Dict[str, str]) -> str:
    """格式化人工确认问题+答案，供ConfirmationIntegrator使用"""
    formatted = []

    for item in confirmation_items:
        number = item.get('number', 'N/A')
        answer = str(answers.get(number, "选项1") or "").strip()
        options = [str(opt).strip() for opt in item.get('options', []) if str(opt).strip()]
        resolved_answer = _resolve_confirmation_answer(answer, options)
        related_function = str(item.get('related_function') or '').strip()
        description = str(item.get('description') or '').strip()
        format_type = str(item.get('format_type') or 'choice').strip()

        lines = [
            "<HUMAN_CONFIRM_START>",
            f"问题编号: {number}",
            f"问题标题: {item.get('title', 'N/A')}",
        ]
        if related_function:
            lines.append(f"关联功能: {related_function}")
        if description and description not in ["未提供描述", "未提供"]:
            lines.append(f"问题说明: {description}")

        lines.extend([
            f"问题格式: {format_type}",
            f"用户原始答案: {answer or '未填写'}",
            f"已解析确认结论: {resolved_answer or answer or '未填写'}",
        ])

        lines.append("<HUMAN_CONFIRM_END>")

        formatted.append("\n".join(lines))

    return "\n".join(formatted)


def _resolve_confirmation_answer(answer: str, options: List[str]) -> str:
    """Resolve short answers like '选项1' or '1' to the full option text when possible."""
    if not answer or not options:
        return answer

    normalized = answer.strip()
    index_match = re.fullmatch(r"(?:选项|option)?\s*([0-9]+)", normalized, flags=re.IGNORECASE)
    if index_match:
        index = int(index_match.group(1)) - 1
        if 0 <= index < len(options):
            return options[index]

    # Some frontends may submit the exact option text or a string containing it.
    for option in options:
        if normalized == option or normalized in option or option in normalized:
            return option

    return answer


def _normalize_steps(steps: Any) -> List[str]:
    """规范化测试步骤为字符串列表"""
    if isinstance(steps, list):
        return [str(s).strip() for s in steps if str(s).strip()]
    elif isinstance(steps, str):
        # 尝试按换行符分割
        lines = [s.strip() for s in steps.split('\n') if s.strip()]
        if len(lines) > 1:
            return lines
        # 尝试按分号分割
        parts = [s.strip() for s in steps.split(';') if s.strip()]
        return parts if len(parts) > 1 else [steps.strip()]
    else:
        return [str(steps)]


def _extract_test_cases_from_markdown(markdown_content: str) -> List[Dict]:
    """从Markdown表格中提取测试用例，使用中文表头（与文本需求格式保持一致）"""
    testcases = []

    # 查找Markdown表格
    lines = markdown_content.split('\n')
    table_started = False
    headers = []

    # 测试用例表格必须包含的关键列名
    required_columns = ['功能模块', '用例编号', '测试步骤', '预期结果']

    def is_testcase_table_header(line: str) -> bool:
        """判断是否为测试用例表格的表头"""
        # 必须是表格行
        if '|' not in line:
            return False
        # 必须包含测试用例特征列名
        matched = sum(1 for col in required_columns if col in line)
        return matched >= 2  # 至少匹配2个关键列名

    def is_separator_line(line: str) -> bool:
        """判断是否为Markdown表格分隔符行"""
        # 分隔符行格式: |:---|:---|  或 |---|---|
        stripped = line.strip()
        if not stripped.startswith('|'):
            return False
        # 分隔符只包含 |, -, :, 空格
        content = stripped.replace('|', '').replace('-', '').replace(':', '').replace(' ', '')
        return len(content) == 0

    for line in lines:
        line = line.strip()

        # 跳过空行
        if not line:
            # 空行可能意味着表格结束
            if table_started:
                # 如果已经解析到测试用例，继续查找下一个可能的表格
                # 否则可能是表格之间的空行
                pass
            continue

        # 检测是否遇到非测试用例的表格或章节标题（停止解析）
        if table_started and '|' in line:
            # 如果是新的表格表头（包含不同的列名），停止当前表格解析
            # 注意：只检查是否是表头行（通常第一列是"PRD章节"等），而不是检查整行内容
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells:
                first_cell = cells[0].replace('*', '').strip()
                # 检查第一列是否是非测试用例表格的特征列名
                if first_cell in ['PRD章节', '章节', '功能点描述', '检查项', '覆盖率', '总用例数']:
                    logger.debug(f"检测到非测试用例表格，停止解析: {line[:50]}...")
                    break

        # 检测测试用例表格表头
        if not table_started and is_testcase_table_header(line):
            headers = [h.strip() for h in line.split('|') if h.strip()]
            table_started = True
            logger.debug(f"检测到测试用例表格表头: {headers}")
            continue

        # 跳过分隔符行
        if table_started and is_separator_line(line):
            continue

        # 解析表格数据行
        if table_started and line.startswith('|'):
            cells = [c.strip() for c in line.split('|')[1:-1]]  # 去掉首尾空元素

            # 过滤掉明显不是测试用例的行（如分隔符残留、表头残留）
            if len(cells) >= 3:
                first_cell = cells[0].replace('*', '').strip()
                # 跳过分隔符行（可能格式不标准）
                if first_cell.startswith(':--') or first_cell.startswith('---'):
                    continue
                # 跳过表头行（可能重复出现）
                if first_cell in ['功能模块', 'PRD章节', '模块', 'Module']:
                    continue

                # 使用中文表头，按原始表格顺序：功能模块|测试场景分类|用例编号|用例名称|...
                testcase = {
                    '功能模块': cells[0] if len(cells) > 0 else '',
                    '测试场景分类': cells[1] if len(cells) > 1 else '',
                    '用例编号': cells[2] if len(cells) > 2 else '',
                    '用例名称': cells[3] if len(cells) > 3 else '',
                    '前置条件': cells[4] if len(cells) > 4 else '',
                    '测试步骤': cells[5] if len(cells) > 5 else '',  # 保持原样，包含<br>标签
                    '预期结果': cells[6] if len(cells) > 6 else '',  # 保持原样，包含<br>标签
                    '优先级': cells[7] if len(cells) > 7 else 'P2',
                    '用例类型': cells[8] if len(cells) > 8 else '功能测试'
                }
                testcases.append(testcase)

        # 如果遇到非表格行（且已经开始解析），检查是否应该重置表格状态
        elif table_started and not line.startswith('|'):
            # 遇到章节标题或分隔线，重置表格状态，继续查找下一个表格
            if line.startswith('#') or line.startswith('---') or line.startswith('==='):
                logger.debug(f"检测到章节分隔，重置表格状态继续查找: {line[:30]}...")
                table_started = False
                headers = []
                # 不再 break，继续查找后续表格

    logger.info(f"从Markdown提取到 {len(testcases)} 个测试用例")
    return testcases


def review_prd_and_generate_questions(prd_path: str, task_name: str, output_dir: str, notes_mgr: NotesManager = None, conv_logger=None) -> Tuple[str, List[Dict], str]:
    """
    评审PRD并生成人工确认问题
    （原 stage1_review_prd，移动到核心模块并改名）

    Args:
        prd_path: PRD文件路径
        task_name: 任务名称
        output_dir: 输出目录
        notes_mgr: 备注管理器（可选）
        conv_logger: 对话日志记录器（可选）

    Returns:
        (prd_content, confirmation_items, review_result)
    """
    import autogen
    from agents.qa_agents.factory import QAAgentFactory

    logger.info("=" * 80)
    logger.info("开始PRD评审 - 提取业务盲点")

    # 1. 加载配置和PRD
    from services.config.model_config_service import load_model_config
    config_list = load_model_config()

    with open(prd_path, 'r', encoding='utf-8') as f:
        prd_content = f.read()

    logger.info(f"加载PRD成功：{len(prd_content)} 字符")

    # 2. 创建Factory和Agent
    factory = QAAgentFactory(config_list=config_list)
    reviewer = factory.create_image_prd_reviewer()

    if not reviewer:
        raise RuntimeError("创建ImagePRDReviewer失败")

    logger.info("ImagePRDReviewer创建成功")

    # 3. 创建UserProxy
    user_proxy = autogen.UserProxyAgent(
        name="HumanUser",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=0,
        code_execution_config=False,
    )

    # 4. 获取备注
    doc_notes = ""
    test_notes = ""
    if notes_mgr and notes_mgr.has_notes():
        doc_notes = notes_mgr.get_notes_for_stage("需求文档补充")
        test_notes = notes_mgr.get_notes_for_stage("测试补充")

    # 5. 评审PRD
    logger.info("开始评审PRD...")

    existing_items_for_prompt = extract_confirmation_items(prd_content)
    existing_questions_text = "无"
    if existing_items_for_prompt:
        lines = []
        for idx, item in enumerate(existing_items_for_prompt, 1):
            title = str(item.get("title") or "未提供标题").strip()
            related = str(item.get("related_function") or "").strip()
            if related:
                lines.append(f"{idx}. {title}（关联功能：{related}）")
            else:
                lines.append(f"{idx}. {title}")
        existing_questions_text = "\n".join(lines)

    prompt = f"""【PRD文档】
{prd_content}

【PRD中已有待确认问题清单】
{existing_questions_text}

---

**评审任务**：
请基于 PRD 原文，对当前功能做行为闭环评审，找出仍未定义清楚、会影响开发实现、测试断言或用户操作预期的问题。

**注意**：
- 只输出新增问题，不要重复上面“已有待确认问题清单”中的问题
- 不要扩展 PRD 范围，不要默认补充导出、移动端、配置化、后台能力等扩展需求
- 按照 system_message 中的格式输出人工确认问题

请输出您新发现的人工确认问题。
"""

    # 添加备注（如果有）
    if doc_notes or test_notes:
        prompt += """

---
补充参考：

"""
        if doc_notes:
            prompt += f"{doc_notes}\n\n"
        if test_notes:
            prompt += f"{test_notes}\n"

    # 调用Agent
    before_usage = StructuredTestcasePipeline._agent_usage_snapshot(reviewer)
    chat_result = user_proxy.initiate_chat(
        recipient=reviewer,
        message=prompt,
        max_turns=1
    )

    # 5. 提取评审结果
    review_result = extract_agent_response(chat_result, "ImagePRDReviewer")
    usage = StructuredTestcasePipeline._agent_usage_delta(reviewer, before_usage)
    record_current_agent_call(
        agent=reviewer,
        prompt=prompt,
        response=review_result,
        usage=usage,
        estimated=usage is None,
    )

    # 清理结果
    if "请评审以下图片分析生成的PRD" in review_result:
        parts = review_result.split("<HUMAN_CONFIRM_START>")
        if len(parts) > 1:
            review_result = "<HUMAN_CONFIRM_START>".join(["", *parts[1:]])

    logger.info(f"评审完成，结果长度: {len(review_result)} 字符")

    # 6. 提取人工确认问题
    # 📝 策略：代码层整合（AI专注发现问题，代码负责去重合并）

    # 6.1 从原始PRD提取已有问题
    original_items = extract_confirmation_items(prd_content)
    logger.info(f"从原PRD提取问题: {len(original_items)} 个")

    # 6.2 从评审结果提取新问题
    review_items = extract_confirmation_items(review_result)
    logger.info(f"从评审结果提取问题: {len(review_items)} 个")

    # 6.3 智能去重和合并
    def calculate_similarity(q1: Dict, q2: Dict) -> float:
        """计算两个问题的相似度（0-1之间）"""
        from difflib import SequenceMatcher

        # 组合标题、关联功能、描述进行比较
        text1 = f"{q1.get('title', '')} {q1.get('related_function', '')} {q1.get('description', '')}"
        text2 = f"{q2.get('title', '')} {q2.get('related_function', '')} {q2.get('description', '')}"

        # 去除标点和空格
        import re
        text1_clean = re.sub(r'[^\w]', '', text1)
        text2_clean = re.sub(r'[^\w]', '', text2)

        if not text1_clean or not text2_clean:
            return 0.0

        return SequenceMatcher(None, text1_clean, text2_clean).ratio()

    confirmation_items = []
    dup_count = 0

    # 先添加原PRD问题
    for item in original_items:
        item['source'] = '原PRD'
        confirmation_items.append(item)

    # 添加评审问题，去重
    for item in review_items:
        # 检查是否与已有问题重复
        is_duplicate = False
        for existing in confirmation_items:
            similarity = calculate_similarity(item, existing)
            if similarity >= 0.85:  # 相似度阈值85%
                is_duplicate = True
                dup_count += 1
                logger.info(f"去重: [{item.get('title', '')[:30]}] 与 [{existing.get('title', '')[:30]}] 相似度 {similarity:.2f}")
                break

        if not is_duplicate:
            item['source'] = '评审新增'
            confirmation_items.append(item)

    # 统一编号
    for idx, item in enumerate(confirmation_items):
        item['number'] = f"Q{idx+1:03d}"

    logger.info(f"✅ 问题整合完成: 总计{len(confirmation_items)}个 (原PRD:{len(original_items)}个, 评审:{len(review_items)}个, 去重:{dup_count}个)")

    # 7. 保存结果
    prd_dir = os.path.join(output_dir, "prd")
    os.makedirs(prd_dir, exist_ok=True)

    # 保存原始PRD（Stage 2生成的版本）
    with open(os.path.join(prd_dir, "01_original_prd.md"), 'w', encoding='utf-8') as f:
        f.write(prd_content)

    # 保存评审结果（包含AI整合后的完整人工确认问题列表）
    with open(os.path.join(prd_dir, "02_review_result.md"), 'w', encoding='utf-8') as f:
        f.write(review_result)

    # 🆕 返回包含Prompt的完整结果
    return {
        'prd_content': prd_content,
        'confirmation_items': confirmation_items,
        'review_result': review_result,
        'prompt': prompt,  # 🆕 返回完整Prompt
        'success': True
    }


def integrate_confirmations(prd_content: str, confirmation_items: List[Dict],
                            answers: Dict[str, str], output_dir: str, notes_mgr: NotesManager = None, conv_logger=None) -> str:
    """
    整合人工确认答案到PRD，生成最终PRD
    （原 stage3_integrate_confirmations，移动到核心模块并改名）

    Args:
        prd_content: 原始PRD内容
        confirmation_items: 确认问题列表
        answers: 确认答案字典
        output_dir: 输出目录
        notes_mgr: 备注管理器（可选）
        conv_logger: 对话日志记录器（可选）

    Returns:
        final_prd
    """
    import autogen
    from agents.qa_agents.factory import QAAgentFactory

    logger.info("=" * 80)
    logger.info("开始整合人工确认 - 生成最终PRD")

    cleaned_prd_content = clean_prd_document(prd_content)
    if cleaned_prd_content and cleaned_prd_content != prd_content:
        logger.info(
            "确认整合前已清理PRD输入中的模型包装/待确认块: %s -> %s 字符",
            len(prd_content),
            len(cleaned_prd_content),
        )
        prd_content = cleaned_prd_content

    # 1. 加载配置
    from services.config.model_config_service import load_model_config
    config_list = load_model_config()

    # 2. 格式化人工确认问题+答案
    confirmations_text = format_confirmations_with_answers(confirmation_items, answers)

    # 3. 创建Factory和Agent
    factory = QAAgentFactory(config_list=config_list)
    integrator = factory.create_confirmation_integrator()

    if not integrator:
        raise RuntimeError("创建ConfirmationIntegrator失败")

    logger.info("ConfirmationIntegrator创建成功")

    # 4. 创建UserProxy
    user_proxy = autogen.UserProxyAgent(
        name="HumanUser",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=0,
        code_execution_config=False,
    )

    # 5. 获取备注
    doc_notes = ""
    if notes_mgr and notes_mgr.has_notes():
        doc_notes = notes_mgr.get_notes_for_stage("需求文档补充")

    # 6. 整合人工确认到PRD
    logger.info("开始整合人工确认...")

    prompt = f"""你是资深产品经理，负责将确认答案整合到PRD中。

【原始PRD】
{prd_content}

【人工确认问题+答案】
{confirmations_text}

【任务】
将确认答案中的信息整合到原始PRD的合适位置。

要求：
1. 保持PRD原有结构
2. 将答案自然地融入相关章节
3. 保持语言风格一致
4. 只整合用户已确认的问题答案，不得把未确认问题、候选选项、参考示例写入最终 PRD
5. 如果原始PRD中仍残留 `<HUMAN_CONFIRM_START>...<HUMAN_CONFIRM_END>` 待确认块，必须忽略这些块本身，只保留已被用户答案明确确认的内容

请输出：
1. 最终完整PRD文档（完整输出，不要省略）
2. 整合清单（说明每个确认整合到哪里）
"""

    # 添加备注（如果有）
    if doc_notes:
        prompt += f"""

---
补充参考：

{doc_notes}
"""

    # 调用Agent
    before_usage = StructuredTestcasePipeline._agent_usage_snapshot(integrator)
    chat_result = user_proxy.initiate_chat(
        recipient=integrator,
        message=prompt,
        max_turns=1
    )

    # 6. 提取最终PRD
    integration_result = extract_agent_response(chat_result, "ConfirmationIntegrator")
    usage = StructuredTestcasePipeline._agent_usage_delta(integrator, before_usage)
    record_current_agent_call(
        agent=integrator,
        prompt=prompt,
        response=integration_result,
        usage=usage,
        estimated=usage is None,
    )

    # 清理结果
    if "【原始PRD】" in integration_result or "【人工确认问题+答案】" in integration_result:
        logger.warning("检测到输出可能包含原始prompt，尝试提取纯PRD内容...")
        lines = integration_result.split('\n')
        prd_lines = []
        in_prd = False
        for line in lines:
            if line.strip().startswith('# ') and '需求' in line:
                in_prd = True
            if in_prd and ('【原始PRD】' in line or '【人工确认问题+答案】' in line or '请输出：' in line):
                break
            if in_prd:
                prd_lines.append(line)

        if prd_lines:
            integration_result = '\n'.join(prd_lines)

    cleaned_integration_result = clean_prd_document(integration_result)
    if cleaned_integration_result and cleaned_integration_result != integration_result:
        logger.info(
            "已清理最终PRD中的模型包装/整合报告: %s -> %s 字符",
            len(integration_result),
            len(cleaned_integration_result),
        )
        integration_result = cleaned_integration_result
    speed_aligned_result = align_playback_speeds_to_sources(integration_result, prd_content, confirmations_text)
    if speed_aligned_result != integration_result:
        logger.info(
            "已按原始PRD和确认答案约束播放倍速枚举: %s -> %s 字符",
            len(integration_result),
            len(speed_aligned_result),
        )
        integration_result = speed_aligned_result

    logger.info(f"整合完成，结果长度: {len(integration_result)} 字符")

    # 7. 保存最终PRD
    prd_dir = os.path.join(output_dir, "prd")
    os.makedirs(prd_dir, exist_ok=True)
    final_prd_file = os.path.join(prd_dir, "04_final_prd.md")
    with open(final_prd_file, 'w', encoding='utf-8') as f:
        f.write(integration_result)
    logger.info(f"保存最终完整PRD: {final_prd_file}")

    # 🆕 返回包含Prompt的完整结果
    return {
        'final_prd': integration_result,
        'prompt': prompt,  # 🆕 返回完整Prompt
        'success': True
    }


def run_testcase_pipeline(base_url: str, final_prd: str, task_name: str, output_dir: str, notes_mgr: NotesManager = None, conv_logger=None) -> List[Dict]:
    """
    运行测试用例生成流程（Test Analyst + Test Case Writer）
    （原 stage4_run_testcase_pipeline，移动到核心模块并改名）

    Args:
        base_url: API基础URL
        final_prd: 最终PRD文档内容
        task_name: 任务名称
        output_dir: 输出目录
        notes_mgr: 备注管理器（可选）
        conv_logger: 对话日志记录器（可选）

    Returns:
        testcases (List[Dict])
    """
    from agents.qa_agents.factory import QAAgentFactory
    from services.generation.structured_testcase_pipeline import StructuredTestcasePipeline

    logger.info("=" * 80)
    logger.info("开始生成测试用例（PRD Knowledge + LU 分包生成）")
    cleaned_final_prd = clean_prd_document(final_prd)
    if cleaned_final_prd and cleaned_final_prd != final_prd:
        logger.info("用例生成前已清理PRD输入: %s -> %s 字符", len(final_prd), len(cleaned_final_prd))
        final_prd = cleaned_final_prd

    # 1. 加载配置
    from services.config.model_config_service import load_model_config
    config_list = load_model_config()

    # 2. 创建Factory和智能体
    factory = QAAgentFactory(config_list=config_list)
    module_test_case_writer = factory.create_module_test_case_writer()
    integration_test_case_writer = factory.create_integration_test_case_writer()
    prd_block_builder = factory.create_prd_block_builder()
    prd_knowledge_builder = factory.create_prd_knowledge_builder()
    test_case_quality_reviewer = factory.create_test_case_quality_reviewer()

    if not all([prd_block_builder, prd_knowledge_builder, module_test_case_writer]):
        raise RuntimeError("创建智能体失败")

    logger.info("智能体创建成功")

    # 3. 获取备注。测试补充只进入 LU 用例生成上下文。
    requirement_notes = ""
    testing_notes = ""
    if notes_mgr and notes_mgr.has_notes():
        requirement_notes = notes_mgr.get_notes_for_stage("需求文档补充")
        testing_notes = notes_mgr.get_notes_for_stage("测试补充")

    pipeline_output_dir = os.path.join(output_dir, "testcase_pipeline")
    pipeline = StructuredTestcasePipeline()
    result = pipeline.run(
        task_id=f"image_{task_name}",
        final_prd=final_prd,
        task_name=task_name,
        output_dir=pipeline_output_dir,
        agents={
            "module_test_case_writer": module_test_case_writer,
            "integration_test_case_writer": integration_test_case_writer,
            "prd_block_builder": prd_block_builder,
            "prd_knowledge_builder": prd_knowledge_builder,
            "test_case_quality_reviewer": test_case_quality_reviewer,
        },
        requirement_notes=requirement_notes,
        testing_notes=testing_notes,
        notification_service=None,
    )

    logger.info(f"结构化测试用例生成完成，成功提取 {len(result.get('testcases') or [])} 个测试用例")

    return {
        'testcases': result.get('testcases', []),
        'test_analysis': result.get('test_analysis', ''),
        'testcases_raw': result.get('testcases_raw', ''),
        'analysis_prompt': result.get('analysis_prompt', ''),
        'testcase_prompt': result.get('testcase_prompt', ''),
        'artifact_dir': result.get('artifact_dir'),
        'artifact_index': result.get('artifact_index'),
        'package_results': result.get('package_results', []),
        'success': True
    }
