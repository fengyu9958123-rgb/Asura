"""
测试用例生成服务，负责生成测试用例
"""

import logging
import os
import json

from services.generation.prd_document_cleaner import clean_prd_document

logger = logging.getLogger(__name__)

class TestGenerationService:
    """测试用例生成服务，生成Excel格式的测试用例"""

    def __init__(self, agent_service, logging_service, task_manager, file_service):
        """初始化测试用例生成服务"""
        self.agent_service = agent_service
        self.logging_service = logging_service
        self.task_manager = task_manager
        self.file_service = file_service

        logger.info("测试用例生成服务初始化完成")

    def generate_test_cases(self, task_id, task=None, notification_service=None, max_rounds=5):
        """生成测试用例。当前只使用 PRD Knowledge 新链路。"""
        try:
            if not task:
                task = self.task_manager.get_task(task_id)

            if not task:
                logger.error(f"任务不存在: {task_id}")
                return False

            return self._generate_test_cases_structured(task_id, task, notification_service)

        except Exception as e:
            logger.exception(f"生成测试用例失败: {e}")
            return False

    def _generate_test_cases_structured(self, task_id, task, notification_service=None):
        """PRD Knowledge 分块、LU 组装与测试用例生成。"""
        try:
            self.task_manager.update_task_status(
                task_id,
                'processing',
                80,
                "正在准备测试用例生成"
            )

            final_prd = task.get('final_prd', '') or task.get('enhanced_prd', '')
            if not final_prd:
                logger.error("PRD文档不存在，无法生成测试用例")
                return False

            cleaned_prd = self._extract_prd_from_marked_response(final_prd)
            logger.info(f"结构化流水线：PRD内容长度 {len(cleaned_prd)}")
            self.task_manager.update_task_status(
                task_id,
                'processing',
                84,
                "正在准备需求上下文"
            )

            agents = self.agent_service.get_agents(task_id)
            if not agents:
                logger.error(f"获取智能体失败: {task_id}")
                return False

            required_agents = [
                'prd_block_builder',
                'prd_knowledge_builder',
            ]
            missing = [agent_name for agent_name in required_agents if not agents.get(agent_name)]
            if not agents.get('module_test_case_writer'):
                missing.append('module_test_case_writer')
            if missing:
                logger.error(f"结构化流水线缺少智能体: {', '.join(missing)}")
                return False

            from services.generation.structured_testcase_pipeline import StructuredTestcasePipeline

            output_dir = os.path.join('outputs', 'testcase_pipeline', task_id)
            pipeline = StructuredTestcasePipeline(logging_service=self.logging_service)
            requirement_notes = str(task.get('notes_requirement') or '')
            testing_notes = str(task.get('notes_testing') or '')
            self.task_manager.update_task_status(
                task_id,
                'processing',
                88,
                "正在设计测试覆盖范围"
            )
            result = pipeline.run(
                task_id=task_id,
                final_prd=cleaned_prd,
                task_name=task.get('name') or task.get('prd_name') or 'testcase_task',
                output_dir=output_dir,
                agents=agents,
                requirement_notes=requirement_notes,
                testing_notes=testing_notes,
                notification_service=notification_service,
            )

            final_test_cases = result.get('testcases') or []
            if not final_test_cases:
                logger.error("结构化流水线未生成测试用例")
                return False

            self.task_manager.update_task_status(
                task_id,
                'processing',
                96,
                "正在整理测试结果"
            )
            prd_name = task.get('prd_name') or task.get('name') or 'test_cases'
            excel_path = self.file_service.save_test_cases_to_excel(
                final_test_cases,
                prd_name,
                task_id
            )
            if not excel_path:
                logger.error("Excel文件保存失败")
                return False

            result_files = task.get('result_files', {}) or {}
            result_files['excel'] = excel_path
            result_files['pipeline_dir'] = result.get('artifact_dir')
            result_files['pipeline_artifact_index'] = result.get('artifact_index')

            self.task_manager.update_task(
                task_id,
                testcases=final_test_cases,
                test_analysis=result.get('test_analysis', ''),
                test_case_writer_messages=json.dumps(result.get('package_messages', []), ensure_ascii=False),
                result_files=result_files
            )

            logger.info(f"结构化测试用例生成完成，共 {len(final_test_cases)} 条，Excel: {excel_path}")

            if notification_service:
                try:
                    notification_service.notify_log(task_id, f"结构化测试用例生成完成，共 {len(final_test_cases)} 条")
                    notification_service.notify_log(task_id, f"Excel文件: {os.path.basename(excel_path)}")
                    notification_service.notify_file_generated(
                        task_id,
                        'excel',
                        os.path.basename(excel_path)
                    )
                except Exception as e:
                    logger.warning(f"发送通知失败，但不影响主流程: {e}")

            return True

        except Exception as e:
            logger.exception(f"结构化测试用例生成失败: {e}")
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
            # 如果提取失败，返回原内容
            return pm_response
