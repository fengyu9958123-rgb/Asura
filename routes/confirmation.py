"""
确认相关API路由 - 处理人工确认功能
适配纯HTTP轮询模式
"""

from flask import Blueprint, request, jsonify
from utils.response import success_response, error_response
from utils.task_identity import resolve_task_identity
import logging

logger = logging.getLogger(__name__)
confirmation_bp = Blueprint('confirmation', __name__)

def register_confirmation_routes(app, generation_service, task_manager):
    """注册确认相关路由
    
    Args:
        app: Flask应用实例
        generation_service: 生成服务实例，用于处理人工确认
        task_manager: 任务管理器实例
    """

    @app.route('/api/confirmation', methods=['POST'])
    def submit_confirmation():
        """提交确认答复
        
        请求参数:
            confirmation_id: 确认ID（可选）
            task_id: 任务ID（可选） 
            answers: 答复内容
            
        返回:
            message: 成功消息
            task_id: 相关任务ID
            
        错误码:
            400: 请求数据为空、缺少必要参数
            500: 提交确认失败
        """
        try:
            data = request.json
            if not data:
                return error_response('请求数据为空', 400)
                
            confirmation_id = data.get('confirmation_id')
            task_id = data.get('task_id')
            answers = data.get('answers')
            confirmed = data.get('confirmed', True)
            
            if not confirmation_id and not task_id:
                return error_response('确认ID或任务ID必须提供', 400)
                
            if not answers:
                return error_response('缺少必要参数: answers', 400)

            if task_id:
                identity = resolve_task_identity(task_id)
                task_id = identity.task_id if identity.is_text and identity.task_id else identity.canonical_id
    
            # 处理确认
            success = generation_service.handle_confirmation(
                confirmation_id=confirmation_id,
                confirmed=confirmed,
                task_id=task_id,
                answers=answers
            )
    
            if not success:
                return error_response('提交确认失败', 500)
        
            return success_response({
                'message': '确认已提交',
                'task_id': task_id or confirmation_id.split(':')[0] if confirmation_id else None
            })
            
        except Exception as e:
            logger.error(f"提交确认失败: {str(e)}")
            return error_response(f"提交确认失败: {str(e)}")
    
    @app.route('/api/tasks/<task_id>/confirm', methods=['POST'])
    def confirm_task(task_id):
        """提交任务确认答复（统一支持文本PRD和图片任务）

        URL参数:
            task_id: 任务ID（可以是 img_task_xxx 或 task_xxx 或 req_mod_xxx）

        请求参数:
            确认答复数据（JSON格式）

        返回:
            message: 成功消息
            task_id: 任务ID

        错误码:
            400: 请求数据为空
            500: 提交任务确认失败
        """
        try:
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            data = request.json
            if not data:
                return error_response('请求数据为空', 400)

            # 判断是图片任务还是文本PRD任务
            # 1. 如果task_id以req_mod_开头，直接是图片任务的module_id
            # 2. 如果task_id以img_task_开头，需要查找对应的module_id
            # 3. 否则是文本PRD任务

            if identity.is_image and identity.module_id:
                # 直接是图片任务的module_id
                module_id = identity.module_id
                logger.info(f"图片任务确认（直接module_id）: module_id={module_id}")
            elif task_id.startswith('img_task_'):
                # 通过generated_task_id查找module_id
                from database.models import DatabaseManager, RequirementModule
                db_manager = DatabaseManager()
                db_manager.initialize()
                session = db_manager.get_session()
                try:
                    module = session.query(RequirementModule).filter_by(generated_task_id=task_id).first()
                    if not module:
                        return error_response('图片任务不存在', 404)
                    module_id = module.id
                    logger.info(f"图片任务确认（通过img_task_id）: task_id={task_id}, module_id={module_id}")
                finally:
                    session.close()
            else:
                # 文本PRD任务
                task = task_manager.get_task(task_id)
                if not task:
                    return error_response('任务不存在', 404)

                logger.info(f"文本PRD任务确认: task_id={task_id}")
                result_files = task.get('result_files') or {}
                if isinstance(result_files, str):
                    try:
                        import json
                        result_files = json.loads(result_files)
                    except Exception:
                        result_files = {}
                if result_files.get('pipeline') == 'text_langgraph':
                    from services.generation.langgraph_text_pipeline import LangGraphTextPipelineRuntimeService
                    LangGraphTextPipelineRuntimeService().continue_after_confirmation(task_id, data)
                    return success_response({
                        'message': '确认已提交，继续生成最终PRD和测试用例',
                        'task_id': task_id
                    })

                success = generation_service.handle_task_confirmation(task_id, data)

                if not success:
                    return error_response('提交确认失败', 500)

                return success_response({
                    'message': '确认已提交',
                    'task_id': task_id
                })

            # 处理图片任务确认
            # 构造用户答案字典 {question_number: answer}
            # 统一编号为 Q001-Q00N，直接用索引生成
            user_answers = {}
            for key, value in data.items():
                # 支持两种格式：answer_0, answer_1, ... 或者 Q001, Q002, ...
                if key.startswith('answer_'):
                    # 提取 answer_ 后面的部分
                    suffix = key.replace('answer_', '')
                    # 检查是否为纯数字
                    if suffix.isdigit():
                        # 根据索引生成问题编号 Q001, Q002, ...
                        idx = int(suffix)
                        question_number = f"Q{idx+1:03d}"
                        user_answers[question_number] = value
                    else:
                        # 非数字后缀（如 human_confirm_1），跳过或使用原始key
                        logger.debug(f"跳过非标准answer字段: {key}")
                        continue
                else:
                    # 直接使用问题编号作为key
                    user_answers[key] = value

            logger.info(f"用户答案: {len(user_answers)} 个, 映射: {list(user_answers.keys())}")

            # 调用 LangGraph 图片流程继续执行；页面交互和接口保持不变
            from services.generation.langgraph_pipeline import LangGraphImagePipelineRuntimeService
            service = LangGraphImagePipelineRuntimeService()
            service.continue_after_confirmation(module_id, user_answers)

            return success_response({
                'message': '确认已提交，继续生成测试用例',
                'task_id': task_id
            })
            
        except Exception as e:
            logger.error(f"提交任务确认失败: {str(e)}", exc_info=True)
            return error_response(f"提交任务确认失败: {str(e)}")
    
    app.register_blueprint(confirmation_bp, url_prefix='/api/confirmation') 
