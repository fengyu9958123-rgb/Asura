"""
文件操作相关API路由
处理文件上传和下载等操作
"""
from flask import request, send_file, Blueprint
import json
import os
from werkzeug.utils import secure_filename
from utils.response import success_response, error_response
from utils.task_identity import resolve_task_identity
import logging
from database.models import DatabaseManager, Task
from services.prd.prd_service import PRDService

logger = logging.getLogger(__name__)
files_bp = Blueprint('files', __name__)

from services.utils.testcase_export import build_fresh_export_from_db


def register_files_routes(app, file_service, generation_service=None):
    """注册文件相关路由
    
    Args:
        app: Flask应用实例
        file_service: 文件服务实例，用于处理文件操作
        generation_service: 生成服务实例（可选），用于创建任务
    """
    
    @app.route('/api/upload', methods=['POST'])
    def upload_prd():
        """兼容上传入口：只创建文本PRD草稿，不再创建旧生成任务。
        
        请求参数:
            file: 上传的文件（multipart/form-data）
            
        返回:
            prd_id: 创建的PRD ID
            id: PRD ID
            name: PRD名称
            message: 成功消息
            
        错误码:
            400: 没有文件上传、未选择文件、文件编码不支持
            500: 文件读取失败、文件上传失败
        """
        try:
            if 'file' not in request.files:
                return error_response('没有文件上传', 400)
                
            file = request.files['file']
            if file.filename == '':
                return error_response('未选择文件', 400)
                
            if file:
                # 先从原始文件名提取PRD名称（支持中文）
                original_filename = file.filename
                prd_name = os.path.splitext(original_filename)[0]
                
                # 然后安全地保存文件
                filename = secure_filename(original_filename)
                
                # 读取文件内容
                try:
                    prd_content = file.read().decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        file.seek(0)
                        prd_content = file.read().decode('gbk')
                    except Exception as e:
                        return error_response(f'文件编码不支持: {str(e)}', 400)
                except Exception as e:
                    return error_response(f'文件读取失败: {str(e)}', 500)

                db_manager = DatabaseManager()
                db_manager.initialize()
                prd_service = PRDService(db_manager, app.config.get('UPLOAD_FOLDER', 'uploads'))
                prd_id = prd_service.create_prd(prd_name or filename, prd_content)

                # 记录日志
                logger.info(f"兼容上传入口创建文本PRD成功: {filename}, PRD={prd_id}")
                
                return success_response({
                    'prd_id': prd_id,
                    'id': prd_id,
                    'name': prd_name,
                    'status': 'draft',
                    'message': '文件上传成功，请通过文本PRD入口启动LangGraph流程'
                })
        except Exception as e:
            logger.error(f"文件上传失败: {str(e)}")
            return error_response(f"文件上传失败: {str(e)}")
            
    # 移除重复的兼容性路由，统一使用 /api/upload
    # @app.route('/api/files/upload', methods=['POST']) 已删除
            
    @app.route('/api/download/<task_id>/<file_type>', methods=['GET'])
    def download_file(task_id, file_type):
        """下载生成的文件
        
        URL参数:
            task_id: 任务ID
            file_type: 文件类型 (excel|json|html)
            
        返回:
            文件下载流
            
        错误码:
            400: 不支持的文件类型、文件名无效
            403: 文件无法访问
            404: 文件不存在
            500: 文件发送失败、文件下载失败
        """
        try:
            identity = resolve_task_identity(task_id)
            canonical_task_id = identity.canonical_id
            # 验证文件类型
            if file_type not in ['excel', 'json', 'html']:
                logger.warning(f"不支持的文件类型: {file_type}")
                return error_response('不支持的文件类型', 400)
            
            # Excel / JSON 始终基于数据库最新测试用例重新生成，避免返回旧文件
            if file_type in ['excel', 'json']:
                file_info = build_fresh_export_from_db(file_service, canonical_task_id, file_type, identity)
                if file_info:
                    file_path = file_info.get('path')
                    filename = file_info.get('name') or os.path.basename(file_path)
                    logger.info("按需生成最新导出文件: task=%s type=%s path=%s", canonical_task_id, file_type, file_path)
                    return send_file(
                        file_path,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/octet-stream'
                    )

            # 获取文件信息（html 等静态产物仍走历史路径）
            file_info = file_service.get_task_result_file(canonical_task_id, file_type)
            if not file_info:
                file_info = _generate_missing_result_file(canonical_task_id, file_type, identity)
            
            if not file_info:
                logger.warning(f"未找到文件: task_id={task_id}, canonical={canonical_task_id}, file_type={file_type}")
                return error_response('文件不存在', 404)
            
            file_path = file_info.get('path') if isinstance(file_info, dict) else file_info
            
            # 验证文件路径
            if not file_path or not os.path.exists(file_path):
                logger.warning(f"文件路径不存在: {file_path}")
                return error_response('文件不存在', 404)
            
            # 验证文件可读性
            if not os.access(file_path, os.R_OK):
                logger.error(f"文件无法读取: {file_path}")
                return error_response('文件无法访问', 403)
            
            # 获取文件名
            filename = os.path.basename(file_path)
            
            # 确保文件名安全
            if not filename or '..' in filename:
                logger.error(f"不安全的文件名: {filename}")
                return error_response('文件名无效', 400)
            
            logger.info(f"准备下载文件: {filename}, 大小: {os.path.getsize(file_path)} bytes")
            
            try:
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=filename,
                    mimetype='application/octet-stream'
                )
            except Exception as send_error:
                logger.error(f"发送文件失败: {str(send_error)}")
                return error_response(f'文件发送失败: {str(send_error)}', 500)
                
        except Exception as e:
            logger.error(f'文件下载失败: task_id={task_id}, file_type={file_type}, error={str(e)}')
            return error_response(f'文件下载失败: {str(e)}', 500)

    def _generate_missing_result_file(task_id, file_type, identity=None):
        """为新LangGraph流程按需生成旧下载接口需要的结果文件。"""
        if file_type not in ['excel', 'json']:
            return None

        file_info = build_fresh_export_from_db(file_service, task_id, file_type, identity)
        if file_info:
            return file_info

        db_manager = DatabaseManager()
        db_manager.initialize()
        session = db_manager.get_session()
        try:
            testcases = None
            prd_name = None
            if identity and identity.is_image and identity.module_id:
                from database.models import RequirementModule
                module = session.query(RequirementModule).filter_by(id=identity.module_id).first()
                if module and module.test_cases_json:
                    testcases = json.loads(module.test_cases_json)
                    prd_name = module.name or module.id
                    task_id = module.task_id or module.generated_task_id or module.id
            else:
                task = session.query(Task).filter_by(id=task_id).first()
                if task:
                    testcases = task.testcases
                    prd_name = task.name or task.prd_id or 'PRD'

            if not testcases:
                return None

            from services.utils.testcase_export import build_export_file_info
            return build_export_file_info(file_service, testcases, prd_name, task_id, file_type)
        finally:
            session.close()
            
    @app.route('/api/files/<file_id>/content', methods=['GET'])
    def get_file_content(file_id):
        """获取文件内容，用于前端预览

        URL参数:
            file_id: 文件ID或任务ID（支持图片任务的req_mod_ID）

        返回:
            content: 文件文本内容

        错误码:
            400: 文件编码不支持、无效的文件ID
            403: 禁止访问
            404: 文件不存在
            500: 文件读取失败、获取文件内容失败
        """
        from utils.security import is_valid_file_id, is_safe_path, get_safe_path

        try:
            # 🔒 安全检查：验证 file_id 格式
            if not is_valid_file_id(file_id):
                logger.warning(f"无效的文件ID格式: {repr(file_id)}")
                return error_response('无效的文件ID', 400)

            # 获取文件信息
            logger.info(f"获取文件内容: {file_id}")

            # 🎨 检查是否为图片任务的RequirementModule ID
            if file_id.startswith('req_mod_'):
                logger.info(f"识别为图片任务Module ID: {file_id}")

                # 🔒 安全检查：验证模块ID格式
                import re
                if not re.match(r'^req_mod_\d{8}_\d{6}$', file_id):
                    logger.warning(f"无效的模块ID格式: {repr(file_id)}")
                    return error_response('无效的模块ID', 400)

                # 从输出目录读取PRD文件
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                base_dir = os.path.join(project_root, 'outputs', 'image_pipeline')

                # 🔒 使用安全的路径拼接
                module_subpath = f'module_{file_id}/prd'
                prd_dir = get_safe_path(base_dir, module_subpath)

                if prd_dir is None:
                    logger.warning(f"路径安全检查失败: {file_id}")
                    return error_response('禁止访问', 403)

                # 尝试读取最终PRD文件（优先级：04_final_prd > version_prd）
                possible_files = ['04_final_prd.md', 'version_prd.md', '01_original_prd.md']

                for filename in possible_files:
                    filepath = os.path.join(prd_dir, filename)
                    # 🔒 再次验证路径安全
                    if not is_safe_path(base_dir, os.path.relpath(filepath, base_dir)):
                        continue
                    if os.path.exists(filepath):
                        logger.info(f"找到图片任务PRD文件: {filepath}")
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                content = f.read()
                                logger.info(f"成功读取图片任务PRD内容，长度={len(content)}")
                                return success_response({
                                    'content': content,
                                    'file_id': file_id,
                                    'source': 'image_pipeline'
                                })
                        except Exception as e:
                            logger.error(f"读取图片任务PRD文件失败: {e}")
                            continue

                # 如果没有找到任何PRD文件
                logger.warning(f"未找到图片任务的PRD文件: {file_id}, 目录: {prd_dir}")
                return error_response('图片任务PRD文件尚未生成，请等待任务完成', 404)

            # 首先尝试在uploads目录中查找匹配的文件（文本PRD任务）
            upload_folder = os.path.abspath(app.config['UPLOAD_FOLDER'])

            # 🔒 安全检查：确保 file_id 不包含路径分隔符
            if '/' in file_id or '\\' in file_id or '..' in file_id:
                logger.warning(f"文件ID包含非法字符: {repr(file_id)}")
                return error_response('无效的文件ID', 400)

            # 查找以file_id开头的文件
            filepath = None
            matching_files = []
            if os.path.exists(upload_folder):
                for filename in os.listdir(upload_folder):
                    if filename.startswith(file_id):
                        file_path = os.path.join(upload_folder, filename)
                        # 🔒 验证路径在 upload_folder 内
                        if os.path.isfile(file_path) and is_safe_path(upload_folder, filename):
                            matching_files.append(file_path)

            if matching_files:
                # 使用第一个匹配的文件
                filepath = matching_files[0]
                logger.info(f"找到匹配文件: {filepath}")
            else:
                # 处理复合ID，如task_id可能包含原始file_id
                if '_' in file_id:
                    # 尝试提取原始文件ID
                    original_file_id = file_id.split('_')[0]

                    # 🔒 验证提取的ID格式
                    if not is_valid_file_id(original_file_id):
                        logger.warning(f"提取的原始ID无效: {repr(original_file_id)}")
                        return error_response('文件不存在', 404)

                    logger.info(f"从复合ID提取原始文件ID: {original_file_id}")

                    # 再次查找匹配的文件
                    for filename in os.listdir(upload_folder):
                        if filename.startswith(original_file_id):
                            file_path = os.path.join(upload_folder, filename)
                            if os.path.isfile(file_path) and is_safe_path(upload_folder, filename):
                                filepath = file_path
                                logger.info(f"通过原始ID找到文件: {filepath}")
                                break
                    else:
                        logger.warning(f"文件不存在: {file_id}")
                        return error_response('文件不存在', 404)
                else:
                    logger.warning(f"文件不存在: {file_id}")
                    return error_response('文件不存在', 404)

            if not filepath or not os.path.exists(filepath):
                logger.warning(f"文件路径不存在: {filepath}")
                return error_response('文件不存在', 404)

            logger.info(f"准备读取文件: {filepath}")

            # 读取文件内容
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    logger.info(f"成功读取文件内容: {file_id}, 长度={len(content)}")
            except UnicodeDecodeError:
                # 尝试使用其他编码
                try:
                    with open(filepath, 'r', encoding='gbk') as f:
                        content = f.read()
                        logger.info(f"使用GBK编码成功读取文件内容: {file_id}, 长度={len(content)}")
                except Exception as e:
                    logger.error(f"文件编码不支持: {str(e)}")
                    return error_response(f'文件编码不支持: {str(e)}', 400)
            except Exception as e:
                logger.error(f"文件读取失败: {str(e)}")
                return error_response(f'文件读取失败: {str(e)}', 500)

            return success_response({'content': content})

        except Exception as e:
            logger.error(f'获取文件内容失败: {str(e)}')
            return error_response(f'获取文件内容失败: {str(e)}')
    
    # 注册Blueprint
    app.register_blueprint(files_bp, url_prefix='/api/files') 
