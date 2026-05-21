"""
图片生成测试用例流程API路由
"""

from flask import Blueprint, request, jsonify
import logging

logger = logging.getLogger(__name__)

# 创建蓝图
image_pipeline_bp = Blueprint('image_pipeline', __name__, url_prefix='/api/image-pipeline')

# 导入服务（延迟导入避免循环依赖）
from services.generation.image_pipeline_service import ImagePipelineService
from services.generation.langgraph_pipeline import LangGraphImagePipelineRuntimeService
from utils.response import success_response, error_response

# ========== API 端点 ==========

@image_pipeline_bp.route('/start', methods=['POST'])
def start_generation():
    """
    启动图片测试用例生成流程

    Request Body:
        {
            "module_id": int,  # 必需
            "user_id": str     # 可选，默认"system"
        }

    Response:
        {
            "code": 0,
            "message": "success",
            "data": {
                "task_id": int,
                "module_id": int,
                "status": "processing",
                "message": "..."
            }
        }
    """
    try:
        data = request.get_json()

        if not data:
            return error_response("请求体不能为空", code=400)

        module_id = data.get('module_id')
        if not module_id:
            return error_response("缺少必需参数: module_id", code=400)

        user_id = data.get('user_id', 'system')

        # 🔒 检查是否有其他任务正在运行（系统限制：单任务运行）
        from utils.task_check import check_running_tasks
        running_task = check_running_tasks()
        if running_task:
            task_name = running_task.get('name', '未知')
            error_message = f"启动失败：任务 \"{task_name}\" 正在运行中，请稍后重试。"
            return error_response(error_message, code=409)

        # 启动流程
        service = LangGraphImagePipelineRuntimeService()
        result = service.start_generation(module_id, user_id)

        # 添加消息到返回数据
        result['message'] = '图片需求任务启动成功'
        return success_response(result)

    except ValueError as e:
        logger.error(f"参数错误: {e}")
        return error_response(str(e), code=400)
    except Exception as e:
        logger.error(f"启动流程失败: {e}", exc_info=True)
        return error_response(f"启动失败: {str(e)}", code=500)


@image_pipeline_bp.route('/progress/<module_id>', methods=['GET'])
def get_progress(module_id):
    """
    获取处理进度

    Response:
        {
            "code": 0,
            "message": "success",
            "data": {
                "module_id": str,
                "status": "processing",  # draft/processing/waiting_confirmation/completed/failed
                "processing_stage": "analyzing_images",  # 当前阶段
                "progress": 50,  # 0-100
                "task_id": str,
                "error_message": str,
                "error_stage": str
            }
        }
    """
    try:
        service = ImagePipelineService()
        progress_data = service.get_progress(module_id)

        return success_response(progress_data)

    except ValueError as e:
        logger.error(f"参数错误: {e}")
        return error_response(str(e), code=404)
    except Exception as e:
        logger.error(f"获取进度失败: {e}", exc_info=True)
        return error_response(f"获取进度失败: {str(e)}", code=500)


@image_pipeline_bp.route('/results/<module_id>', methods=['GET'])
def get_results(module_id):
    """
    获取生成结果
    
    Response:
        {
            "code": 0,
            "message": "success",
            "data": {
                "module_id": int,
                "module_name": str,
                "status": "completed",
                "prd_version": str,  # 版本PRD内容
                "prd_final": str,  # 最终PRD内容
                "confirmation_questions": str,  # JSON字符串
                "confirmation_answers": str,  # JSON字符串
                "test_analysis": str,
                "test_cases_raw": str,
                "test_cases_json": str,  # JSON字符串
                "prd_file_path": str,
                "test_cases_file_path": str
            }
        }
    """
    try:
        service = ImagePipelineService()
        results = service.get_results(module_id)
        
        return success_response(results)
        
    except ValueError as e:
        logger.error(f"参数错误: {e}")
        return error_response(str(e), code=404)
    except Exception as e:
        logger.error(f"获取结果失败: {e}", exc_info=True)
        return error_response(f"获取结果失败: {str(e)}", code=500)


@image_pipeline_bp.route('/logs/<module_id>', methods=['GET'])
def get_logs(module_id):
    """
    获取流程日志
    
    Query Parameters:
        - stage: 可选，指定阶段名称
    
    Response:
        {
            "code": 0,
            "message": "success",
            "data": {
                "main": "主日志内容...",
                "stage1_analyzing_images": "阶段1日志...",
                "stage2_generating_prd": "阶段2日志...",
                ...
                "performance": "性能日志..."
            }
        }
    """
    try:
        from services.notifications.image_pipeline_logger import get_pipeline_logs
        
        logs = get_pipeline_logs(module_id)
        
        if not logs:
            return error_response(f"未找到模块 {module_id} 的日志", code=404)
        
        # 如果指定了stage参数，只返回特定阶段的日志
        stage = request.args.get('stage')
        if stage and stage in logs:
            return success_response({stage: logs[stage]})
        
        return success_response(logs)
        
    except Exception as e:
        logger.error(f"获取日志失败: {e}", exc_info=True)
        return error_response(f"获取日志失败: {str(e)}", code=500)


@image_pipeline_bp.route('/ai-responses/<module_id>', methods=['GET'])
def get_ai_responses(module_id):
    """
    获取AI响应记录
    
    Query Parameters:
        - agent_name: 可选，筛选特定Agent的响应
    
    Response:
        {
            "code": 0,
            "message": "success",
            "data": [
                {
                    "timestamp": "2023-10-28T10:30:45",
                    "agent_name": "ImageAnalyst",
                    "prompt": "...",
                    "response": "...",
                    "prompt_length": 1000,
                    "response_length": 2000,
                    "metadata": {...}
                },
                ...
            ]
        }
    """
    try:
        from services.notifications.image_pipeline_logger import get_ai_responses as get_responses
        
        agent_name = request.args.get('agent_name')
        responses = get_responses(module_id, agent_name)
        
        if not responses:
            return error_response(f"未找到模块 {module_id} 的AI响应记录", code=404)
        
        return success_response(responses)
        
    except Exception as e:
        logger.error(f"获取AI响应失败: {e}", exc_info=True)
        return error_response(f"获取AI响应失败: {str(e)}", code=500)


# ========== 健康检查 ==========

@image_pipeline_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return success_response({"status": "healthy", "message": "Image Pipeline API is running"})


@image_pipeline_bp.route('/regenerate-all-excel', methods=['POST'])
def regenerate_all_excel():
    """强制重新生成所有已完成任务的Excel文件（用于更新表头格式）"""
    import json
    from database.models import db_manager, RequirementModule
    from services.storage.file_service import FileService
    import app_config
    
    try:
        file_service = FileService(app_config.UPLOAD_FOLDER)
        session = db_manager.get_session()
        regenerated_count = 0
        regenerated_tasks = []
        
        try:
            # 查找所有已完成且有测试用例的任务
            modules = session.query(RequirementModule).filter(
                RequirementModule.status == 'completed',
                RequirementModule.test_cases_json.isnot(None)
            ).all()
            
            for module in modules:
                logger.info(f"重新生成任务: {module.name} (ID: {module.id})")
                
                try:
                    testcases_list = json.loads(module.test_cases_json)
                    
                    if not testcases_list:
                        continue
                    
                    # 强制重新生成 Excel 文件
                    excel_file_path = file_service.save_test_cases_to_excel(
                        test_cases=testcases_list,
                        prd_name=module.name or "image_task",
                        task_id=module.task_id or module.id
                    )
                    
                    # 更新数据库
                    module.test_cases_file_path = excel_file_path
                    session.commit()
                    
                    regenerated_count += 1
                    regenerated_tasks.append({
                        'id': module.id,
                        'name': module.name,
                        'excel_path': excel_file_path
                    })
                    
                    logger.info(f"✅ 成功重新生成: {excel_file_path}")
                    
                except Exception as e:
                    logger.error(f"处理任务 {module.id} 失败: {e}")
                    session.rollback()
            
            return success_response({
                'regenerated_count': regenerated_count,
                'regenerated_tasks': regenerated_tasks,
                'message': f'成功重新生成 {regenerated_count} 个任务的 Excel 文件'
            })
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"重新生成Excel文件失败: {e}", exc_info=True)
        return error_response(f"重新生成失败: {str(e)}", code=500)


@image_pipeline_bp.route('/fix-missing-excel', methods=['POST'])
def fix_missing_excel():
    """临时修复接口：为缺失Excel的已完成任务生成Excel文件"""
    import json
    from database.models import db_manager, RequirementModule
    from services.storage.file_service import FileService
    import app_config
    
    try:
        # 初始化 FileService（需要upload_folder参数）
        file_service = FileService(app_config.UPLOAD_FOLDER)
        session = db_manager.get_session()
        fixed_count = 0
        fixed_tasks = []
        
        try:
            # 查找已完成但没有 Excel 文件的任务
            modules = session.query(RequirementModule).filter(
                RequirementModule.status == 'completed',
                RequirementModule.test_cases_json.isnot(None)
            ).all()
            
            for module in modules:
                # 检查是否缺少 Excel 文件
                if module.test_cases_file_path:
                    continue
                
                logger.info(f"修复任务: {module.name} (ID: {module.id})")
                
                try:
                    # 解析测试用例
                    testcases_list = json.loads(module.test_cases_json)
                    
                    if not testcases_list:
                        continue
                    
                    # 生成 Excel 文件
                    excel_file_path = file_service.save_test_cases_to_excel(
                        test_cases=testcases_list,
                        prd_name=module.name or "image_task",
                        task_id=module.task_id or module.id
                    )
                    
                    # 更新数据库
                    module.test_cases_file_path = excel_file_path
                    session.commit()
                    
                    fixed_count += 1
                    fixed_tasks.append({
                        'id': module.id,
                        'name': module.name,
                        'excel_path': excel_file_path
                    })
                    
                    logger.info(f"✅ 成功生成: {excel_file_path}")
                    
                except Exception as e:
                    logger.error(f"处理任务 {module.id} 失败: {e}")
                    session.rollback()
            
            return success_response({
                'fixed_count': fixed_count,
                'fixed_tasks': fixed_tasks,
                'message': f'成功修复 {fixed_count} 个任务的 Excel 文件'
            })
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"修复Excel文件失败: {e}", exc_info=True)
        return error_response(f"修复失败: {str(e)}", code=500)
