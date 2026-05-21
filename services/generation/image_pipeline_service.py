"""
图片生成测试用例完整流程服务
整合 test_generate_prd_from_images.py 和 test_image_prd_complete.py

设计参考: docs/IMAGE_TO_TESTCASE_DETAILED_DESIGN.md
验证参考: docs/IMAGE_TO_TESTCASE_FLOW_VERIFICATION.md
"""

import os
import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

# 注意：在实际项目中，DatabaseManager 可能在 database.models 中
# 这里假设项目结构为标准结构
try:
    from database.models import DatabaseManager, RequirementModule, Task, TaskStatus
except ImportError:
    # 处理导入错误
    logging.warning("无法导入 DatabaseManager，请检查导入路径")
    DatabaseManager = None
    RequirementModule = None
    Task = None
    TaskStatus = None

logger = logging.getLogger(__name__)

class ImagePipelineService:
    """图片生成测试用例流程服务"""
    
    def __init__(self):
        if DatabaseManager is None:
            raise RuntimeError("DatabaseManager 未正确导入")
        self.db_manager = DatabaseManager()
        self.db_manager.initialize()
    
    # ========== 主流程入口 ==========
    
    def start_generation(self, module_id: int, user_id: str = "system") -> Dict[str, Any]:
        """
        启动图片测试用例生成流程
        
        Args:
            module_id: 需求模块ID
            user_id: 用户ID
            
        Returns:
            包含任务ID的字典
        """
        session = self.db_manager.get_session()
        
        try:
            # 1. 验证模块存在且有图片
            module = session.query(RequirementModule).filter_by(id=module_id).first()
            if not module:
                raise ValueError(f"需求模块不存在: {module_id}")
            
            if not module.images or len(module.images) == 0:
                raise ValueError("需求模块没有上传图片")
            
            # 检查状态：阻止正在处理的任务重复启动
            if module.status in ["processing", "waiting_confirmation"]:
                raise ValueError("任务正在处理中，请勿重复启动")
            
            # 2. 生成任务ID（用于日志追踪，但不创建Task对象）
            import uuid
            task_id = f"img_task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"

            # 注意：图片需求不创建Task对象，只使用RequirementModule管理
            # Task表是为文本PRD设计的，图片需求有自己的管理流程

            # 3. 更新模块状态
            module.status = "processing"
            module.task_id = task_id  # 保存task_id用于日志追踪
            module.generated_task_id = task_id  # 同时更新旧字段以保持兼容
            module.processing_stage = "initializing"
            module.progress = 0
            module.error_message = None
            module.error_stage = None
            session.commit()
            
            # 4. 启动后台线程执行流程
            thread = threading.Thread(
                target=self._run_pipeline,
                args=(module_id, task_id, user_id),
                daemon=True
            )
            thread.start()

            logger.info(f"✅ 图片流程已启动: module_id={module_id}, task_id={task_id}")

            return {
                "task_id": task_id,
                "module_id": module_id,
                "status": "processing",
                "message": "流程已启动，请等待处理完成"
            }
            
        except Exception as e:
            session.rollback()
            logger.error(f"❌ 启动图片流程失败: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    # ========== 后台处理流程 ==========
    
    def _run_pipeline(self, module_id: int, task_id: str, user_id: str):
        """
        后台执行完整流程（在独立线程中）
        """
        # 初始化统一日志器
        from services.notifications.unified_task_logger import UnifiedTaskLogger
        
        pipeline_logger = UnifiedTaskLogger(task_id, 'image_pipeline')
        pipeline_logger.log_task_start({'module_id': module_id, 'user_id': user_id})
        
        pipeline_start_time = time.time()
        
        try:
            pipeline_logger.main_logger.info(f"🚀 开始执行图片流程: module_id={module_id}, task_id={task_id}")
            
            # 阶段1: 图片分析
            with pipeline_logger.log_stage(1, 'analyzing_images', '图片分析'):
                self._update_progress(module_id, "analyzing_images", 10, "正在分析图片...")
                self._update_task(task_id, completion_percentage=10, current_step='分析图片')
                analyses = self._stage1_analyze_images(module_id, pipeline_logger)
            
            # 阶段2: 生成版本PRD
            with pipeline_logger.log_stage(2, 'generating_prd', 'PRD生成'):
                self._update_progress(module_id, "generating_prd", 30, "正在生成PRD文档...")
                self._update_task(task_id, completion_percentage=30, current_step='生成PRD文档')
                prd_content, prd_file = self._stage2_generate_prd(module_id, analyses, pipeline_logger)
            
            # 阶段3: PRD审核（提取确认问题）
            with pipeline_logger.log_stage(3, 'reviewing_prd', 'PRD审核'):
                self._update_progress(module_id, "reviewing_prd", 50, "正在审核PRD...")
                self._update_task(task_id, completion_percentage=50, current_step='审核PRD')
                questions = self._stage3_review_prd(module_id, prd_content, pipeline_logger)
            
            # ✅ 人工确认：保存确认问题后等待用户输入
            if questions and len(questions) > 0:
                pipeline_logger.main_logger.info(f"✋ 发现 {len(questions)} 个确认问题，等待人工确认...")

                # 更新任务状态为 waiting_confirmation
                from database.models import TaskStatus
                self._update_task(
                    task_id,
                    status=TaskStatus.WAITING_CONFIRMATION,
                    completion_percentage=55,
                    current_step=f"等待人工确认({len(questions)}个问题)"
                )

                # 记录日志并返回（停止执行，等待用户确认）
                pipeline_logger.log_task_end('waiting_confirmation', f'等待人工确认 {len(questions)} 个问题')
                pipeline_logger.main_logger.info("⏸️  流程暂停，等待用户在前端提交确认答案")
                return  # ← 关键：停止执行，等待用户确认

            # 如果没有确认问题，使用PRD内容继续执行测试阶段
            pipeline_logger.main_logger.info("ℹ️  无需人工确认，直接使用PRD生成测试用例")
            final_prd = prd_content  # 使用原始PRD内容

            # 阶段6: 生成测试用例（无需确认的情况）
            with pipeline_logger.log_stage(6, 'generating_testcases', '测试用例生成'):
                self._update_progress(module_id, "generating_testcases", 70, "正在生成测试用例...")
                self._update_task(task_id, completion_percentage=70, current_step='生成测试用例')
                test_results = self._stage6_generate_testcases(module_id, final_prd, pipeline_logger)

            # 阶段7: 保存结果
            with pipeline_logger.log_stage(7, 'saving_results', '结果保存'):
                self._update_progress(module_id, "saving_results", 90, "正在保存结果...")
                self._update_task(task_id, completion_percentage=90, current_step='保存结果')
                self._stage7_save_results(module_id, task_id, test_results)

            # 标记完成
            pipeline_duration = time.time() - pipeline_start_time
            pipeline_logger.log_task_end('success', '流程完成（无需确认）')
            self._update_progress(module_id, "completed", 100, "任务完成")
            self._mark_complete(module_id, task_id)
            pipeline_logger.main_logger.info(f"✅ 图片流程执行成功（无需确认）: module_id={module_id}")
            return
            
        except Exception as e:
            pipeline_duration = time.time() - pipeline_start_time
            pipeline_logger.log_task_end('failed', str(e))
            
            # 记录详细错误
            import traceback
            pipeline_logger.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                exception=e
            )
            
            pipeline_logger.main_logger.error(f"❌ 图片流程执行失败: {e}")
            self._mark_failed(module_id, task_id, str(e))
    
    def continue_after_confirmation(self, module_id: int, user_answers: Dict[str, str]):
        """
        用户确认后继续执行剩余流程（Stage 5-7）
        
        Args:
            module_id: 模块ID
            user_answers: 用户确认答案字典 {question_number: answer}
        """
        from services.notifications.unified_task_logger import UnifiedTaskLogger
        
        # 1. 获取module和task信息
        module = self._get_module(module_id)
        if not module:
            raise ValueError(f"模块不存在: {module_id}")
        
        task_id = module.task_id
        if not task_id:
            raise ValueError(f"模块 {module_id} 没有关联的任务ID")

        # 注意：图片需求可能没有Task对象，这是正常的
        # task_id 仅用于日志追踪
        
        # 2. 初始化logger（追加模式）
        pipeline_logger = UnifiedTaskLogger(task_id, 'image_pipeline')
        pipeline_logger.main_logger.info(f"🔄 继续执行图片流程（用户已确认）: module_id={module_id}")
        
        # 3. 获取之前保存的PRD和确认问题
        prd_content = module.prd_version_content
        if not prd_content:
            raise ValueError(f"模块 {module_id} 缺少PRD内容")
        
        confirmation_questions_str = module.confirmation_questions
        if not confirmation_questions_str:
            raise ValueError(f"模块 {module_id} 缺少确认问题")
        
        confirmation_questions = json.loads(confirmation_questions_str)
        
        # 4. 保存用户答案到数据库
        self._update_module(module_id, confirmation_answers=json.dumps(user_answers, ensure_ascii=False))
        
        pipeline_logger.main_logger.info(f"✅ 收到用户确认: {len(user_answers)} 个答案")
        
        # 5. 启动后台线程继续执行
        thread = threading.Thread(
            target=self._continue_pipeline_in_background,
            args=(module_id, task_id, prd_content, confirmation_questions, user_answers),
            daemon=True
        )
        thread.start()
        
        pipeline_logger.main_logger.info("🚀 后台线程已启动，继续执行 Stage 5-7")
    
    def _continue_pipeline_in_background(
        self, 
        module_id: int, 
        task_id: str, 
        prd_content: str,
        confirmation_questions: List[Dict],
        user_answers: Dict[str, str]
    ):
        """
        在后台线程中继续执行 Stage 5-7
        """
        from services.notifications.unified_task_logger import UnifiedTaskLogger
        
        pipeline_logger = UnifiedTaskLogger(task_id, 'image_pipeline')
        pipeline_start_time = time.time()
        
        try:
            # 更新任务状态为 processing
            from database.models import TaskStatus
            self._update_task(task_id, status=TaskStatus.PROCESSING, completion_percentage=60, current_step='整合确认结果')
            
            # 阶段5: 集成确认结果到PRD
            with pipeline_logger.log_stage(5, 'integrating_confirmations', '确认集成'):
                self._update_progress(module_id, "integrating_confirmations", 70, "正在集成确认结果...")
                self._update_task(task_id, completion_percentage=70, current_step='整合确认结果')
                final_prd = self._stage5_integrate_confirmations(
                    module_id, prd_content, confirmation_questions, user_answers, pipeline_logger
                )
            
            # 阶段6: 生成测试用例
            with pipeline_logger.log_stage(6, 'generating_testcases', '测试用例生成'):
                self._update_progress(module_id, "generating_testcases", 85, "正在生成测试用例...")
                self._update_task(task_id, completion_percentage=85, current_step='生成测试用例')
                test_results = self._stage6_generate_testcases(module_id, final_prd, pipeline_logger)
            
            # 阶段7: 保存结果
            with pipeline_logger.log_stage(7, 'saving_results', '结果保存'):
                self._update_progress(module_id, "saving_results", 95, "正在保存结果...")
                self._update_task(task_id, completion_percentage=95, current_step='保存结果')
                self._stage7_save_results(module_id, task_id, test_results)
            
            # 完成
            pipeline_duration = time.time() - pipeline_start_time
            pipeline_logger.log_task_end('success')
            
            self._update_progress(module_id, "completed", 100, "生成完成！")
            self._update_task(task_id, completion_percentage=100, current_step='生成完成')
            self._mark_complete(module_id, task_id)
            
            pipeline_logger.main_logger.info(f"✅ 图片流程执行成功: module_id={module_id}, 耗时 {pipeline_duration:.2f}s")
            
        except Exception as e:
            pipeline_duration = time.time() - pipeline_start_time
            pipeline_logger.log_task_end('failed', str(e))
            
            # 记录详细错误
            pipeline_logger.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                exception=e
            )
            
            pipeline_logger.main_logger.error(f"❌ 图片流程执行失败: {e}")
            self._mark_failed(module_id, task_id, str(e))
    
    # ========== 各阶段实现 ==========
    
    def _stage1_analyze_images(self, module_id: int, logger: 'UnifiedTaskLogger') -> Dict[str, Dict]:
        """
        阶段1: 分析模块图片
        直接调用 test_generate_prd_from_images.py 的 analyze_module_images
        保持 Prompt 完全不变
        """
        from services.generation.image_prd_core import analyze_module_images
        from agents.qa_agents.factory import QAAgentFactory
        
        module = self._get_module(module_id)
        stage_logger = logger.stage_loggers.get('stage1')
        
        # 1. 创建 ImageAnalyst Agent
        config_list = self._load_config()
        factory = QAAgentFactory(config_list=config_list)
        image_analyst = factory.create_image_analyst()
        
        stage_logger.info(f"创建 ImageAnalyst 完成")
        
        # 2. 准备 module_info (符合原脚本的数据结构)
        output_dir = self._get_output_dir(module_id)
        os.makedirs(output_dir, exist_ok=True)
        
        images_info = []
        for img in (module.images or []):
            # 使用 original_name 提取变更类型，因为变更类型标签在原始文件名中
            original_name = img.get('original_name') or img.get('name') or os.path.basename(img.get('path', ''))
            images_info.append({
                'filename': original_name,
                'path': img.get('path'),
                'change_type': self._get_change_type(module, original_name)
            })
        
        module_info = {
            'module_name': module.name,
            'description': module.description or '',
            'images': images_info
        }
        
        stage_logger.info(f"准备分析 {len(images_info)} 张图片")
        
        # 3. 调用原有函数（保持 Prompt 完全不变）
        notes_mgr = self._get_notes_manager(module)
        
        start_time = time.time()
        analysis_result = analyze_module_images(
            image_analyst=image_analyst,
            module_info=module_info,
            output_dir=output_dir,
            notes_mgr=notes_mgr,
            conv_logger=None  # 可选
        )
        duration = time.time() - start_time
        
        logger.log_performance_metric('analyze_images', duration)
        
        # 4. 提取分析内容
        if not analysis_result.get('success'):
            raise RuntimeError(f"图片分析失败: {analysis_result.get('error', '未知错误')}")
        
        analysis_text = analysis_result.get('image_analysis', '')
        full_prompt = analysis_result.get('prompt', '')  # 🆕 获取完整Prompt
        stage_logger.info(f"✅ 图片分析完成，分析内容长度: {len(analysis_text)} 字符，耗时 {duration:.2f}s")
        
        # 5. 保存AI响应（包含完整Prompt + 图片分类信息）
        metadata = {
            'module_name': module.name,
            'images_count': len(images_info),
            'duration': duration
        }
        
        # 🆕 加入图片分类统计（如果有）
        if 'classification_summary' in analysis_result:
            metadata['classification_summary'] = analysis_result['classification_summary']
        
        logger.save_ai_response(
            agent_name='ImageAnalyst',
            prompt=full_prompt or f"分析模块: {module.name}, {len(images_info)}张图片",  # 🆕 优先使用完整Prompt
            response=analysis_text,
            metadata=metadata
        )
        
        # 6. 保存到数据库
        analyses_dict = {module.name: analysis_result}
        self._update_module(module_id, module_analyses=json.dumps(analyses_dict, ensure_ascii=False))
        
        return analyses_dict
    
    def _stage2_generate_prd(self, module_id: int, analyses: Dict, logger: 'ImagePipelineLogger') -> tuple:
        """
        阶段2: 生成版本PRD
        直接调用 test_generate_prd_from_images.py 的 generate_version_prd
        保持 Prompt 完全不变
        """
        from services.generation.image_prd_core import generate_version_prd
        from agents.qa_agents.factory import QAAgentFactory
        
        module = self._get_module(module_id)
        stage_logger = logger.stage_loggers.get('stage2')
        
        # 1. 创建 ImageIntegrationAnalyst Agent
        config_list = self._load_config()
        factory = QAAgentFactory(config_list=config_list)
        prd_generator = factory.create_image_integration_analyst()
        
        stage_logger.info("创建 ImageIntegrationAnalyst 完成")
        
        # 2. 准备 modules_results (符合原脚本的数据结构)
        # 注意：必须包含 module_info，因为 generate_version_prd 需要访问 result['module_info']
        modules_results = []
        for mod_name, analysis_result in analyses.items():
            if analysis_result.get('success'):
                result = {
                    'module_info': analysis_result.get('module_info', {}),
                    'image_analysis': analysis_result.get('image_analysis', ''),
                    'success': True
                }
                
                # 🆕 传递图片分类信息（如果有）
                if 'classification_summary' in analysis_result:
                    result['classification_summary'] = analysis_result['classification_summary']
                if 'images_classification' in analysis_result:
                    result['images_classification'] = analysis_result['images_classification']
                
                modules_results.append(result)
        
        stage_logger.info(f"准备生成版本PRD，包含 {len(modules_results)} 个成功模块")
        
        # 3. 调用原有函数（保持 Prompt 完全不变）
        output_dir = self._get_output_dir(module_id)
        notes_mgr = self._get_notes_manager(module)
        
        start_time = time.time()
        
        prd_result = generate_version_prd(
            prd_generator=prd_generator,
            version_name=module.name,
            modules_results=modules_results,
            output_dir=output_dir,
            notes_mgr=notes_mgr,
            conv_logger=None  # 可选
        )
        
        duration = time.time() - start_time
        logger.log_performance_metric('generate_prd', duration)
        
        # 4. 提取结果
        if not prd_result or not prd_result.get('success'):
            # 检查是否有详细的错误日志
            raise RuntimeError("PRD生成失败：generate_version_prd 返回了 None，请检查API配置和余额")
        
        prd_file = prd_result.get('prd_file')
        prd_content = prd_result.get('prd_content', '')
        full_prompt = prd_result.get('prompt', '')  # 🆕 获取完整Prompt
        
        if not os.path.exists(prd_file):
            raise RuntimeError(f"PRD文件生成失败：文件不存在 {prd_file}")
        
        stage_logger.info(f"✅ PRD生成完成，长度: {len(prd_content)} 字符，耗时 {duration:.2f}s")
        
        # 5. 保存AI响应（包含完整Prompt）
        logger.save_ai_response(
            agent_name='ImageIntegrationAnalyst',
            prompt=full_prompt or f"整合 {len(modules_results)} 个模块生成PRD",  # 🆕 优先使用完整Prompt
            response=prd_content,
            metadata={
                'version_name': module.name,
                'modules_count': len(modules_results),
                'duration': duration
            }
        )
        
        # 6. 保存到数据库
        self._update_module(module_id, prd_version_content=prd_content, prd_file_path=prd_file)
        
        return prd_content, prd_file
    
    def _stage3_review_prd(self, module_id: int, prd_content: str, logger: 'UnifiedTaskLogger') -> List[Dict]:
        """
        阶段3: PRD审核，提取确认问题
        直接调用 test_image_prd_complete.py 的 stage1_review_prd
        保持 Prompt 完全不变
        """
        from services.generation.image_prd_core import review_prd_and_generate_questions
        
        module = self._get_module(module_id)
        stage_logger = logger.stage_loggers.get('stage3')
        
        output_dir = self._get_output_dir(module_id)
        notes_mgr = self._get_notes_manager(module)
        
        # 保存PRD到临时文件（stage1_review_prd需要文件路径）
        prd_temp_file = os.path.join(output_dir, 'temp_prd.md')
        with open(prd_temp_file, 'w', encoding='utf-8') as f:
            f.write(prd_content)
        
        stage_logger.info("开始PRD审核...")
        start_time = time.time()
        
        # 调用核心函数（返回字典格式）
        review_result_dict = review_prd_and_generate_questions(
            prd_path=prd_temp_file,
            task_name=module.name,
            output_dir=output_dir,
            notes_mgr=notes_mgr,
            conv_logger=None  # 可选
        )
        
        duration = time.time() - start_time
        logger.log_performance_metric('review_prd', duration)
        
        # 提取结果
        confirmation_items = review_result_dict.get('confirmation_items', [])
        review_result = review_result_dict.get('review_result', '')
        full_prompt = review_result_dict.get('prompt', '')  # 🆕 获取完整Prompt
        
        stage_logger.info(f"✅ PRD审核完成，提取 {len(confirmation_items)} 个确认问题，耗时 {duration:.2f}s")
        
        # 保存AI响应（包含完整Prompt）
        logger.save_ai_response(
            agent_name='ImagePRDReviewer',
            prompt=full_prompt or "评审PRD文档",  # 🆕 优先使用完整Prompt
            response=review_result,
            metadata={
                'questions_count': len(confirmation_items),
                'duration': duration
            }
        )
        
        # 保存到数据库（同时清除旧答案，避免显示上一次的答案）
        self._update_module(
            module_id, 
            confirmation_questions=json.dumps(confirmation_items, ensure_ascii=False),
            confirmation_answers=None  # 🆕 清除旧答案
        )
        
        return confirmation_items
    
    def _stage5_integrate_confirmations(
        self, 
        module_id: int, 
        prd_content: str, 
        questions: List[Dict],
        answers: Dict,
        logger: 'ImagePipelineLogger'
    ) -> str:
        """
        阶段5: 集成确认结果到PRD
        直接调用 test_image_prd_complete.py 的 stage3_integrate_confirmations
        保持 Prompt 完全不变
        """
        from services.generation.image_prd_core import integrate_confirmations
        
        module = self._get_module(module_id)
        stage_logger = logger.stage_loggers.get('stage5')
        
        output_dir = self._get_output_dir(module_id)
        notes_mgr = self._get_notes_manager(module)
        
        stage_logger.info("开始集成确认结果到PRD...")
        start_time = time.time()
        
        # 调用核心函数（返回字典格式）
        integration_result = integrate_confirmations(
            prd_content=prd_content,
            confirmation_items=questions,
            answers=answers,
            output_dir=output_dir,
            notes_mgr=notes_mgr,
            conv_logger=None  # 可选
        )
        
        duration = time.time() - start_time
        logger.log_performance_metric('integrate_confirmations', duration)
        
        # 提取结果
        final_prd = integration_result.get('final_prd', '')
        full_prompt = integration_result.get('prompt', '')  # 🆕 获取完整Prompt
        
        stage_logger.info(f"✅ 确认集成完成，最终PRD长度: {len(final_prd)} 字符，耗时 {duration:.2f}s")
        
        # 保存AI响应（包含完整Prompt）
        logger.save_ai_response(
            agent_name='ConfirmationIntegrator',
            prompt=full_prompt or "集成确认结果到PRD",  # 🆕 优先使用完整Prompt
            response=final_prd,
            metadata={
                'questions_count': len(questions),
                'duration': duration
            }
        )
        
        # 保存到数据库
        self._update_module(module_id, prd_final_content=final_prd)
        
        # 同时更新 Task 的 prd_content
        module = self._get_module(module_id)
        if module.task_id:
            self._update_task(module.task_id, prd_content=final_prd)
        
        return final_prd
    
    def _stage6_generate_testcases(self, module_id: int, final_prd: str, logger: 'ImagePipelineLogger') -> Dict:
        """
        阶段6: 生成测试用例
        直接调用 test_image_prd_complete.py 的 stage4_run_testcase_pipeline
        保持 Prompt 完全不变
        """
        from services.generation.image_prd_core import run_testcase_pipeline
        
        module = self._get_module(module_id)
        stage_logger = logger.stage_loggers.get('stage6')
        
        output_dir = self._get_output_dir(module_id)
        notes_mgr = self._get_notes_manager(module)
        
        stage_logger.info("开始生成测试用例...")
        start_time = time.time()
        
        # 调用核心函数（返回字典格式）
        testcase_result = run_testcase_pipeline(
            base_url="",  # 空字符串，函数内部会自动处理
            final_prd=final_prd,
            task_name=module.name,
            output_dir=output_dir,
            notes_mgr=notes_mgr,
            conv_logger=None  # 可选
        )
        
        duration = time.time() - start_time
        logger.log_performance_metric('generate_testcases', duration)
        
        # 提取结果
        testcases_list = testcase_result.get('testcases', [])
        test_analysis = testcase_result.get('test_analysis', '')
        testcases_raw = testcase_result.get('testcases_raw', '')
        analysis_prompt = testcase_result.get('analysis_prompt', '')  # PRD Knowledge prompt
        testcase_prompt = testcase_result.get('testcase_prompt', '')  # ModuleTestCaseWriter prompt
        artifact_dir = testcase_result.get('artifact_dir')
        artifact_index = testcase_result.get('artifact_index')
        
        stage_logger.info(f"✅ 测试用例生成完成，耗时 {duration:.2f}s，共 {len(testcases_list) if testcases_list else 0} 个用例")
        
        # 保存AI响应到统一日志（包含完整Prompt）
        if test_analysis:
            logger.save_ai_response(
                agent_name='PRDKnowledgePipeline',
                prompt=analysis_prompt or "测试分析",  # 🆕 优先使用完整Prompt
                response=test_analysis,
                metadata={'duration': duration, 'testcases_count': len(testcases_list) if testcases_list else 0}
            )
        
        if testcases_raw:
            logger.save_ai_response(
                agent_name='ModuleTestCaseWriter',
                prompt=testcase_prompt or "生成测试用例",  # 🆕 优先使用完整Prompt
                response=testcases_raw,
                metadata={'duration': duration, 'testcases_count': len(testcases_list) if testcases_list else 0}
            )
        
        # 将测试用例列表转换为JSON
        testcases_json = json.dumps(testcases_list, ensure_ascii=False, indent=2) if testcases_list else "[]"
        
        # 构造返回结果
        test_results = {
            'test_analysis': test_analysis,
            'testcases_raw': testcases_raw,
            'testcases_json': testcases_json,
            'testcases_list': testcases_list,
            'artifact_dir': artifact_dir,
            'artifact_index': artifact_index
        }
        
        # 保存到数据库
        update_data = {
            'test_analysis': test_analysis,
            'test_cases_raw': testcases_raw,
            'test_cases_json': testcases_json
        }
        if artifact_dir or artifact_index:
            update_data['generation_result'] = {
                'artifact_dir': artifact_dir,
                'artifact_index': artifact_index
            }
        
        self._update_module(module_id, **update_data)
        
        # 同时更新 Task
        module = self._get_module(module_id)
        if module.task_id:
            task_update = {'test_analysis': test_analysis}
            if testcases_json:
                task_update['testcases'] = testcases_json
            self._update_task(module.task_id, **task_update)
        
        return test_results
    
    def _stage7_save_results(self, module_id: int, task_id: str, test_results: Dict):
        """
        阶段7: 保存最终结果到文件和数据库（包括生成Excel文件）
        """
        from services.storage.file_service import FileService
        import app_config
        
        module = self._get_module(module_id)
        
        # 生成 Excel 文件（如果有测试用例）
        excel_file_path = None
        testcases_list = test_results.get('testcases_list', [])
        
        if testcases_list:
            logger.info(f"开始生成 Excel 文件，测试用例数: {len(testcases_list)}")
            file_service = FileService(app_config.UPLOAD_FOLDER)
            
            try:
                # 调用 FileService 生成 Excel
                excel_file_path = file_service.save_test_cases_to_excel(
                    test_cases=testcases_list,
                    prd_name=module.name or "image_task",
                    task_id=task_id
                )
                logger.info(f"✅ Excel 文件生成成功: {excel_file_path}")
                
                # 更新模块的 test_cases_file_path
                self._update_module(module_id, test_cases_file_path=excel_file_path)
                
            except Exception as e:
                logger.error(f"生成 Excel 文件失败: {e}", exc_info=True)
        else:
            logger.warning("没有测试用例，跳过 Excel 文件生成")
        
        # 准备 result_files
        result_files = {
            'prd_file': module.prd_file_path,
            'testcases_file': excel_file_path or module.test_cases_file_path,
            'output_dir': self._get_output_dir(module_id),
            'pipeline_dir': test_results.get('artifact_dir'),
            'pipeline_artifact_index': test_results.get('artifact_index')
        }
        
        # 更新 Task
        self._update_task(task_id, result_files=result_files)
        
        logger.info(f"✅ 结果已保存: PRD={module.prd_file_path}, 测试用例={excel_file_path or '无'}")
    
    # ========== 数据库辅助方法 ==========
    
    def _get_module(self, module_id: int) -> 'RequirementModule':
        """获取需求模块"""
        session = self.db_manager.get_session()
        try:
            module = session.query(RequirementModule).filter_by(id=module_id).first()
            if not module:
                raise ValueError(f"需求模块不存在: {module_id}")
            return module
        finally:
            session.close()
    
    def _update_module(self, module_id: int, **kwargs):
        """更新模块字段"""
        session = self.db_manager.get_session()
        try:
            module = session.query(RequirementModule).filter_by(id=module_id).first()
            if module:
                for key, value in kwargs.items():
                    setattr(module, key, value)
                session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
    
    def _get_task(self, task_id: str) -> Optional['Task']:
        """获取任务（图片需求可能没有Task对象）"""
        session = self.db_manager.get_session()
        try:
            task = session.query(Task).filter_by(id=task_id).first()
            return task
        finally:
            session.close()

    def _update_task(self, task_id: str, **kwargs):
        """更新任务字段（图片需求可能没有Task对象，静默跳过）"""
        session = self.db_manager.get_session()
        try:
            task = session.query(Task).filter_by(id=task_id).first()
            if task:
                for key, value in kwargs.items():
                    setattr(task, key, value)
                session.commit()
            else:
                # 图片需求没有Task对象，这是正常的，静默跳过
                logger.debug(f"Task不存在（图片需求）: {task_id}，跳过更新")
        except Exception as e:
            session.rollback()
            logger.warning(f"更新Task失败: {e}")
            # 不抛出异常，避免影响图片流程
        finally:
            session.close()
    
    # ========== 辅助方法 ==========
    
    def _load_config(self) -> List[Dict]:
        """加载 OAI_CONFIG_LIST 配置文件"""
        from services.config.model_config_service import load_model_config

        config_list = load_model_config()
        if not config_list:
            raise FileNotFoundError("模型配置为空，请先在模型配置页面设置模型")
        return config_list
    
    def _get_notes_manager(self, module: 'RequirementModule') -> Optional['NotesManager']:
        """
        获取 NotesManager 实例
        如果模块有 notes_requirement 或 notes_testing，创建 NotesManager
        """
        from services.utils.notes_manager import NotesManager
        
        if module.notes_requirement or module.notes_testing:
            # 创建临时笔记文件
            output_dir = self._get_output_dir(module.id)
            notes_file = os.path.join(output_dir, 'notes.md')
            
            with open(notes_file, 'w', encoding='utf-8') as f:
                if module.notes_requirement:
                    f.write("## 需求文档补充\n\n")
                    f.write(module.notes_requirement)
                    f.write("\n\n")
                
                if module.notes_testing:
                    f.write("## 测试补充\n\n")
                    f.write(module.notes_testing)
                    f.write("\n\n")
            
            return NotesManager(notes_file)
        
        return None
    
    def _get_change_type(self, module: 'RequirementModule', filename: str) -> str:
        """
        从文件名中提取变更类型标签
        文件名格式: [新增]_[背景]_01_功能名称.png 或 [优化]_功能名称.png
        """
        import re
        
        # 优先从文件名中提取变更类型（第一个方括号）
        match = re.match(r'^\[([^\]]+)\]', filename)
        if match:
            change_type = match.group(1)
            logger.info(f"从文件名提取到变更类型: {change_type} (文件: {filename})")
            return change_type
        
        # 备选方案：从 notes 中提取（兼容旧数据）
        if module.notes:
            try:
                if isinstance(module.notes, str):
                    notes_dict = json.loads(module.notes)
                else:
                    notes_dict = module.notes
                
                file_note = notes_dict.get(filename, {})
                change_type = file_note.get('change_type', '未指定')
                if change_type != '未指定':
                    logger.info(f"从notes提取到变更类型: {change_type} (文件: {filename})")
                    return change_type
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
        
        logger.warning(f"未能提取变更类型，文件: {filename}")
        return "未指定"
    
    def _get_output_dir(self, module_id: int) -> str:
        """获取模块输出目录"""
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        output_dir = os.path.join(project_root, 'outputs', 'image_pipeline', f'module_{module_id}')
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    
    def _update_progress(
        self, 
        module_id: int, 
        stage: str, 
        progress: int, 
        message: str = ""
    ):
        """更新处理进度"""
        try:
            self._update_module(module_id, processing_stage=stage, progress=progress)
            logger.info(f"📊 进度更新: module={module_id}, stage={stage}, progress={progress}%")
            # TODO: 可以通过 WebSocket 推送实时进度
        except Exception as e:
            logger.error(f"❌ 更新进度失败: {e}")
    
    def _mark_complete(self, module_id: int, task_id: str):
        """标记任务完成"""
        try:
            self._update_module(module_id, status="completed", progress=100)
            self._update_task(task_id, status=TaskStatus.COMPLETED)  # 图片需求会静默跳过
            logger.info(f"✅ 任务完成: module={module_id}, task={task_id}")
        except Exception as e:
            logger.error(f"❌ 标记完成失败: {e}")

    def _mark_failed(self, module_id: int, task_id: str, error_msg: str):
        """标记任务失败"""
        try:
            module = self._get_module(module_id)
            self._update_module(module_id, status="failed", error_message=error_msg, error_stage=module.processing_stage)
            self._update_task(task_id, status=TaskStatus.FAILED)  # 图片需求会静默跳过
            logger.error(f"❌ 任务失败: module={module_id}, task={task_id}, error={error_msg}")
        except Exception as e:
            logger.error(f"❌ 标记失败失败: {e}")
    
    # ========== 查询方法 ==========
    
    def get_progress(self, module_id: int) -> Dict[str, Any]:
        """获取处理进度"""
        module = self._get_module(module_id)
        if not module:
            raise ValueError(f"需求模块不存在: {module_id}")
        
        return {
            "module_id": module_id,
            "status": module.status,
            "processing_stage": module.processing_stage,
            "progress": module.progress,
            "task_id": module.task_id,
            "error_message": module.error_message,
            "error_stage": module.error_stage
        }
    
    def get_results(self, module_id: int) -> Dict[str, Any]:
        """获取生成结果"""
        module = self._get_module(module_id)
        if not module:
            raise ValueError(f"需求模块不存在: {module_id}")
        
        return {
            "module_id": module_id,
            "module_name": module.name,
            "status": module.status,
            "prd_version": module.prd_version_content,
            "prd_final": module.prd_final_content,
            "confirmation_questions": module.confirmation_questions,
            "confirmation_answers": module.confirmation_answers,
            "test_analysis": module.test_analysis,
            "test_cases_raw": module.test_cases_raw,
            "test_cases_json": module.test_cases_json,
            "prd_file_path": module.prd_file_path,
            "test_cases_file_path": module.test_cases_file_path,
            "generation_result": module.generation_result
        }
