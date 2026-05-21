"""
分析服务模块，负责PRD分析和智能体交互
"""

import logging
import os
import json
from datetime import datetime

from services.generation.llm_response_cleaner import strip_model_reasoning
from services.generation.prd_document_cleaner import clean_prd_document

logger = logging.getLogger(__name__)

class AnalysisService:
    """分析服务，负责与AI智能体交互进行PRD分析"""

    def __init__(self, agent_service, logging_service, task_manager):
        """初始化分析服务"""
        self.agent_service = agent_service
        self.logging_service = logging_service
        self.task_manager = task_manager

        logger.info("分析服务初始化完成")

    def analyze_prd(self, task_id):
        """分析PRD文档"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"任务不存在: {task_id}")
                return False

            logger.info(f"开始分析PRD: {task_id}, 名称: {task.get('name', '')}")

            # 获取PRD内容
            prd_content = task.get('prd_content', '')

            # 调试日志：检查PRD内容
            logger.info(f"获取到PRD内容，长度为: {len(str(prd_content))}")
            logger.debug(f"PRD内容前100字符: {str(prd_content)[:100]}")

            if not prd_content or len(str(prd_content)) < 10:
                # 尝试从文件直接读取
                if 'prd_id' in task:
                    prd_id = task.get('prd_id')
                    logger.warning(f"PRD内容为空或过短，尝试从文件加载: {prd_id}")
                    try:
                        # 尝试直接从上传目录读取
                        from pathlib import Path
                        uploads_dir = Path("uploads")
                        for file_path in uploads_dir.glob("*"):
                            if prd_id in file_path.name:
                                logger.info(f"找到PRD文件: {file_path}")
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    prd_content = f.read()
                                    # 更新任务内容
                                    task['prd_content'] = prd_content
                                    self.task_manager.update_task(task_id, prd_content=prd_content)
                                    break
                    except Exception as e:
                        logger.error(f"从文件加载PRD内容失败: {e}")

            # 再次检查内容
            if not prd_content or len(str(prd_content)) < 10:
                logger.error(f"PRD内容为空或过短，无法分析: {task_id}")
                return False

            # 确保智能体已初始化
            if not self.agent_service.get_agents(task_id):
                logger.info(f"为任务 {task_id} 初始化智能体")
                if not self.agent_service.initialize_agents(task_id):
                    logger.error(f"智能体初始化失败: {task_id}")
                    return False

            # 获取智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents:
                logger.error(f"获取智能体失败: {task_id}")
                return False

            product_manager = agents['product_manager']

            # 构造提示词 - 严格与gui_main.py一致
            prompt = f"""请基于以下PRD文档，输出一份更完善的需求文档，为后续测试架构师讨论做准备。
---
{prd_content}
---

输出应该格式清晰，内容较原文更加丰富
"""

            # 调试日志：查看构造的完整提示词
            logger.info(f"提示词长度: {len(prompt)}")
            logger.debug(f"提示词前200字符: {prompt[:200]}")

            # 使用ProductManager智能体生成分析
            self.logging_service.log_system_event("PRD分析", f"ProductManager开始分析PRD: {task.get('name')}")

            # 初始化消息历史 - 与gui_main.py保持一致
            product_manager_messages = [
                {"role": "user", "content": prompt}
            ]

            # 调试日志：确认发送给AI的消息
            logger.info(f"发送给ProductManager的消息长度: {len(product_manager_messages[0]['content'])}")

            # 添加任务消息记录
            self.task_manager.add_message(task_id, "System", "正在分析PRD文档...")

            try:
                # 调用智能体 - 根据pyautogen最新API添加sender=None参数
                response = strip_model_reasoning(product_manager.generate_reply(
                    messages=product_manager_messages,
                    sender=None
                ))

                if not response:
                    logger.error(f"ProductManager分析PRD失败: {task_id}")
                    return False

                # 更新消息历史
                product_manager_messages.append({
                    "role": "assistant",
                    "content": response
                })

                # 记录AI回复 - 完整保存，不截断
                self.task_manager.add_message(task_id, "ProductManager", response)

                # 更新任务中的分析结果
                self.task_manager.update_task(
                    task_id,
                    product_manager_analysis=response,
                    product_manager_messages=product_manager_messages
                )

                return True

            except Exception as e:
                logger.error(f"AI生成回复时出错: {e}")
                self.task_manager.add_log(task_id, "ERROR", f"AI分析PRD时发生错误: {str(e)}")
                return False

        except Exception as e:
            logger.exception(f"分析PRD过程中发生异常: {e}")
            return False

    def test_architect_phase(self, task_id):
        """TestArchitect提出问题阶段"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"任务不存在: {task_id}")
                return False

            logger.info(f"开始TestArchitect提问阶段: {task_id}")

            # 获取智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents:
                logger.error(f"获取智能体失败: {task_id}")
                return False

            test_architect = agents['test_architect']

            # 获取之前的PRD分析结果
            prd_content = task.get('prd_content', '')
            pm_analysis = task.get('product_manager_analysis', '')

            # 构造TestArchitect的提示词 - 严格与gui_main.py一致
            prompt = f"""作为测试架构师，你需要审查以下PRD和产品经理的分析，提出问题以确保测试用例的完整性。

## 原始PRD:
{prd_content}

## 产品经理的分析:
{pm_analysis}

请提出5-8个关键问题，这些问题应该关注:
1. 边界条件
2. 异常流程
3. 性能考虑
4. 兼容性要求
5. 安全性考虑

这些问题将帮助我们设计更全面的测试用例。请用清晰的编号列出问题。
"""

            # 使用TestArchitect智能体生成问题
            self.logging_service.log_system_event("TestArchitect提问", f"TestArchitect开始分析并提问: {task_id}")

            # 初始化消息历史
            test_architect_messages = [
                {"role": "user", "content": prompt}
            ]

            # 发送消息给TestArchitect
            response = strip_model_reasoning(test_architect.generate_reply(
                messages=test_architect_messages
            ))

            if not response:
                logger.error(f"TestArchitect提问失败: {task_id}")
                return False

            # 更新消息历史
            test_architect_messages.append({
                "role": "assistant",
                "content": response
            })

            # 更新任务中的问题 - 使用新的字段名
            # 更新任务中的测试架构师问题
            self.task_manager.update_task(
                task_id,
                architect_questions=response,
                test_architect_questions=response,
                test_architect_messages=test_architect_messages
            )

            logger.info(f"TestArchitect提问完成: {task_id}")
            return True

        except Exception as e:
            logger.exception(f"TestArchitect提问失败: {e}")
            return False

    def pm_response_phase(self, task_id):
        """ProductManager回答问题阶段"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"任务不存在: {task_id}")
                return False

            logger.info(f"开始ProductManager回答阶段: {task_id}")

            # 获取智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents:
                logger.error(f"获取智能体失败: {task_id}")
                return False

            product_manager = agents['product_manager']

            # 获取之前的PRD分析和TestArchitect的问题
            prd_content = task.get('prd_content', '')
            pm_analysis = task.get('product_manager_analysis', '')
            ta_questions = task.get('test_architect_questions', '')

            # 构造ProductManager的提示词 - 强调确认标签使用
            prompt = f"""作为产品经理，请回答测试架构师提出的以下问题:

## 原始PRD:
{prd_content}

## 你之前的分析:
{pm_analysis}

## 测试架构师的问题:
{ta_questions}

**❗️ 重要提醒：**
1. **逐一回答每个问题**：必须对每个问题都给出回应，不能遗漏任何问题
2. **判断确认需求**：对每个问题评估是否基于原始PRD能够给出明确答案
3. **使用确认标签**：如果原始PRD中没有明确信息或存在歧义，必须在回答中使用以下格式：
```
<HUMAN_CONFIRM_START>
问题标题: [具体问题描述]
确认点:
1. [选项1的详细描述和影响分析]
2. [选项2的详细描述和影响分析]
3. [如有第三个选项]
<HUMAN_CONFIRM_END>
```
请针对每个问题提供详细回答，说明产品的预期行为、边界条件和异常处理方式。对于确实无法从原始PRD中确定的内容，请务必使用上述确认标签格式标记出来。
"""

            # 使用ProductManager智能体回答问题
            self.logging_service.log_system_event("ProductManager回答", f"ProductManager开始回答问题: {task_id}")

            # 初始化消息历史
            product_manager_response_messages = [
                {"role": "user", "content": prompt}
            ]

            # 发送消息给ProductManager
            response = strip_model_reasoning(product_manager.generate_reply(
                messages=product_manager_response_messages
            ))

            if not response:
                logger.error(f"ProductManager回答问题失败: {task_id}")
                return False

            # 更新消息历史
            product_manager_response_messages.append({
                "role": "assistant",
                "content": response
            })

            # 更新任务中的回答
            task['product_manager_response'] = response

            # 如果之前已有消息历史，则追加
            if 'product_manager_messages' not in task:
                task['product_manager_messages'] = []

            task['product_manager_messages'].extend(product_manager_response_messages)

            # 从产品经理回复中提取确认项
            from services.utils.confirmation_utils import extract_confirmation_items
            confirmation_items = extract_confirmation_items(response)
            if confirmation_items and len(confirmation_items) > 0:
                logger.info(f"从产品经理回复中提取到 {len(confirmation_items)} 个确认项")
                self.task_manager.set_confirmation_items(task_id, confirmation_items)
                # 记录确认项内容便于调试
                for idx, item in enumerate(confirmation_items):
                    logger.debug(f"确认项 {idx+1}: {item.get('question', '无标题')}")
                # 更新任务中的ProductManager回答
            update_data = {
                'product_manager_response': response,
                'product_manager_response_messages': product_manager_response_messages
            }

            # 如果有确认项，更新状态
            if confirmation_items and len(confirmation_items) > 0:
                update_data['status'] = 'waiting_confirmation'

            self.task_manager.update_task(task_id, **update_data)

            logger.info(f"ProductManager回答完成: {task_id}")
            return True

        except Exception as e:
            logger.exception(f"ProductManager回答失败: {e}")
            return False

    def finalize_prd_phase(self, task_id):
        """ProductManager最终整理PRD阶段"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                logger.error(f"任务不存在: {task_id}")
                return False

            logger.info(f"开始ProductManager最终PRD整理阶段: {task_id}")

            # 获取智能体
            agents = self.agent_service.get_agents(task_id)
            if not agents:
                logger.error(f"获取智能体失败: {task_id}")
                return False

            product_manager = agents['product_manager']

            # 获取所有相关内容
            prd_content = task.get('prd_content', '')
            pm_analysis = task.get('product_manager_analysis', '')
            ta_questions = task.get('architect_questions') or task.get('test_architect_questions', '')  # 优先使用新字段名
            pm_response = task.get('product_manager_response', '')
            confirmation_results = task.get('confirmation_results', [])

            # 构建人工确认摘要
            confirmation_summary = ""
            if confirmation_results:
                confirmation_summary = "\n\n## 人工确认结果\n"
                for idx, result in enumerate(confirmation_results):
                    answers = result.get('answers', '')
                    if isinstance(answers, dict):
                        # 如果answers是字典，提取所有答案
                        answer_texts = []
                        for key, value in answers.items():
                            if key.startswith('answer_') and value:
                                answer_texts.append(value)
                        answers = '; '.join(answer_texts)

                    confirmation_summary += f"{idx+1}. {answers}\n"

            # 构造ProductManager的最终整理提示词
            prompt = f"""作为产品经理，请基于以下所有信息，整理出一份最完善、最详细的PRD文档：

## 原始PRD:
{prd_content}

## 你之前的需求分析:
{pm_analysis}

## 测试架构师的问题:
{ta_questions}

## 你对问题的回答:
{pm_response}

{confirmation_summary}

请整合以上所有信息，输出一份完善的PRD文档。要求：
1. 保持原始PRD的核心功能和业务逻辑
2. 整合你之前的需求分析和对测试架构师问题的回答
3. 融入人工确认的所有答案和澄清
4. 确保文档详细、完整、无歧义
5. 适合作为测试用例生成的最终依据

请输出完整的PRD文档：
"""

            # 使用ProductManager智能体生成最终PRD
            self.logging_service.log_system_event("最终PRD整理", f"ProductManager开始最终PRD整理: {task_id}")

            # 初始化消息历史
            final_prd_messages = [
                {"role": "user", "content": prompt}
            ]

            # 发送消息给ProductManager
            response = strip_model_reasoning(product_manager.generate_reply(
                messages=final_prd_messages
            ))

            if not response:
                logger.error(f"ProductManager最终PRD整理失败: {task_id}")
                return False

            # 更新消息历史
            final_prd_messages.append({
                "role": "assistant",
                "content": response
            })

            # 更新任务中的最终PRD
            # 更新任务中的最终PRD
            self.task_manager.update_task(
                task_id,
                final_prd=response,
                final_prd_messages=final_prd_messages
            )

            logger.info(f"ProductManager最终PRD整理完成: {task_id}")
            return True

        except Exception as e:
            logger.exception(f"ProductManager最终PRD整理失败: {e}")
            return False

    def _extract_prd_from_marked_response(self, pm_response):
        """从ProductManager的回复中提取标记内的PRD文档内容

        根据 <PRD_DOCUMENT_START> 和 <PRD_DOCUMENT_END> 标记提取纯净的PRD文档
        """
        try:
            prd_content = clean_prd_document(pm_response)
            if prd_content != str(pm_response or "").strip():
                logger.info(f"成功清理PRD文档，内容长度: {len(prd_content)}")
            else:
                logger.warning("未找到可清理的PRD包装，返回原始内容")
            return prd_content

        except Exception as e:
            logger.error(f"提取标记内PRD文档失败: {e}")
            return pm_response

    def _extract_confirmation_items(self, response):
        """从ProductManager回复中提取需要人工确认的项目"""
        try:
            # 统一使用confirmation_utils中的实现，避免重复逻辑
            from services.utils.confirmation_utils import extract_confirmation_items
            confirmation_items = extract_confirmation_items(response)

            logger.info(f"提取到 {len(confirmation_items)} 个确认项")
            for i, item in enumerate(confirmation_items):
                logger.debug(f"确认项 {i+1}: id={item.get('id', 'unknown')}, 内容长度={len(item.get('question_details', ''))}")

            return confirmation_items

        except Exception as e:
            logger.error(f"提取确认项失败: {e}")
            return []

    def _extract_confirmation_title(self, content):
        """从确认项内容中提取问题标题用于去重

        Args:
            content: 确认项内容

        Returns:
            str: 提取的标题，用于去重判断
        """
        try:
            import re

            # 尝试多种标题格式匹配
            title_patterns = [
                r'问题标题[：:]\s*(.+?)(?:\n|$)',
                r'\*\*问题标题\*\*[：:]\s*(.+?)(?:\n|$)',
                r'标题[：:]\s*(.+?)(?:\n|$)',
                r'^(.+?)(?:\n确认点|$)',  # 如果没有明确标题标记，取第一行
            ]

            for pattern in title_patterns:
                match = re.search(pattern, content.strip(), re.MULTILINE)
                if match:
                    title = match.group(1).strip()
                    # 清理标题中的markdown标记
                    title = re.sub(r'\*\*(.+?)\*\*', r'\1', title)
                    if title and len(title) > 5:  # 确保标题有意义
                        return title

            # 如果都无法匹配，使用内容前50字符作为标题
            return content[:50].strip()

        except Exception as e:
            logger.error(f"提取确认项标题失败: {e}")
            return content[:50].strip() if content else ""
