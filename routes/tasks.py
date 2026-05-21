"""
任务相关API路由
"""

from flask import Blueprint, request, jsonify
from utils.response import success_response, error_response
from utils.task_identity import resolve_task_identity
import logging
import json
import os
from pathlib import Path

logger = logging.getLogger(__name__)
tasks_bp = Blueprint('tasks', __name__)

def register_task_routes(app, task_manager, generation_service=None):
    """注册任务相关路由"""

    def _resolve_text_task_id(task_id):
        identity = resolve_task_identity(task_id)
        return identity.task_id if identity.is_text and identity.task_id else str(task_id or "")

    def _get_image_module_by_task_id(task_id):
        """Return RequirementModule for req_mod_* or img_task_* ids."""
        from database.models import RequirementModule, db_manager

        identity = resolve_task_identity(task_id)
        if identity.is_image and identity.module_id:
            task_id = identity.module_id

        session = db_manager.get_session()
        try:
            if task_id.startswith('req_mod_'):
                module = session.query(RequirementModule).filter_by(id=task_id).first()
            else:
                module = session.query(RequirementModule).filter(
                    (RequirementModule.generated_task_id == task_id) |
                    (RequirementModule.task_id == task_id)
                ).first()
            if module:
                session.expunge(module)
            return module
        finally:
            session.close()

    def _read_json_file(path, default=None):
        try:
            if not path:
                return default
            file_path = Path(path)
            if not file_path.exists():
                return default
            return json.loads(file_path.read_text(encoding='utf-8'))
        except Exception as exc:
            logger.warning(f"读取JSON文件失败: {path}, error={exc}")
            return default

    def _resolve_langgraph_output_dir(module):
        if not module:
            return None
        generation_result = module.generation_result or {}
        if isinstance(generation_result, str):
            try:
                generation_result = json.loads(generation_result)
            except Exception:
                generation_result = {}
        output_dir = generation_result.get('output_dir') if isinstance(generation_result, dict) else None
        if output_dir and Path(output_dir).exists():
            return Path(output_dir)
        fallback = Path('outputs') / 'image_pipeline_langgraph' / f'module_{module.id}'
        return fallback if fallback.exists() else None

    def _resolve_text_langgraph_output_dir(task):
        if not task:
            return None
        result_files = task.get('result_files') or {}
        if isinstance(result_files, str):
            try:
                result_files = json.loads(result_files)
            except Exception:
                result_files = {}
        output_dir = result_files.get('output_dir') if isinstance(result_files, dict) else None
        if output_dir and Path(output_dir).exists():
            return Path(output_dir)
        fallback = Path('outputs') / 'text_pipeline_langgraph' / f'task_{task.get("id")}'
        return fallback if fallback.exists() else None

    def _is_text_langgraph_task(task):
        result_files = (task or {}).get('result_files') or {}
        if isinstance(result_files, str):
            try:
                result_files = json.loads(result_files)
            except Exception:
                result_files = {}
        return isinstance(result_files, dict) and result_files.get('pipeline') == 'text_langgraph'

    def _load_text_langgraph_test_results(task):
        """从文本 LangGraph 输出目录中回填测试结果。"""
        if not task or not _is_text_langgraph_task(task):
            return {}

        result_files = task.get('result_files') or {}
        if isinstance(result_files, str):
            try:
                result_files = json.loads(result_files)
            except Exception:
                result_files = {}

        candidate_paths = []
        if isinstance(result_files, dict):
            test_results_path = result_files.get('test_results_path')
            if test_results_path:
                candidate_paths.append(Path(test_results_path))

        output_dir = _resolve_text_langgraph_output_dir(task)
        if output_dir:
            candidate_paths.append(Path(output_dir) / 'testcase_pipeline' / 'test_results.json')

        for candidate_path in candidate_paths:
            payload = _read_json_file(candidate_path, default={}) or {}
            if isinstance(payload, dict) and payload:
                return payload

        return {}

    def _read_ai_response_messages(ai_responses_dir, source):
        messages = []
        if not ai_responses_dir or not Path(ai_responses_dir).exists():
            return messages
        stage_map = {
            'ImageAnalyst': ('02_image_analysis', '图片分析'),
            'ImageIntegrationAnalyst': ('03_prd_generation', 'PRD生成'),
            'ImagePRDReviewer': ('04_prd_review', 'PRD审核'),
            'ConfirmationIntegrator': ('06_confirmation_integrate', '确认整合'),
        }
        for sequence, file_path in enumerate(sorted(Path(ai_responses_dir).glob('*.json'))):
            ai_data = _read_json_file(file_path, default={}) or {}
            timestamp = ai_data.get('timestamp', '')
            agent_name = ai_data.get('agent_name', 'assistant')
            stage_key, stage_name = stage_map.get(agent_name, ('', ''))
            if ai_data.get('prompt'):
                messages.append({
                    'role': f'{agent_name} Prompt',
                    'sender': f'{agent_name} Prompt',
                    'content': ai_data['prompt'],
                    'timestamp': timestamp,
                    'sequence': sequence * 2,
                    'source': source,
                    'stage_key': stage_key,
                    'stage_name': stage_name,
                    'io_type': 'input',
                    'title': f'{stage_name}输入' if stage_name else '输入',
                })
            if ai_data.get('response'):
                messages.append({
                    'role': agent_name,
                    'sender': agent_name,
                    'content': ai_data['response'],
                    'timestamp': timestamp,
                    'sequence': sequence * 2 + 1,
                    'source': source,
                    'stage_key': stage_key,
                    'stage_name': stage_name,
                    'io_type': 'output',
                    'title': f'{stage_name}输出' if stage_name else '输出',
                })
        return messages

    def _read_text_langgraph_messages(output_dir, base_sequence=0):
        messages = []
        if not output_dir:
            return messages
        pairs = [
            (
                '03_text_prd_logic_reviewer',
                'TextPRDLogicReviewer',
                '03_prd_logic_review',
                'PRD逻辑审查',
            ),
            (
                '05_text_final_prd_integrator',
                'TextFinalPRDIntegrator',
                '05_final_prd_integrate',
                '最终PRD整合',
            ),
        ]
        for index, (name, role, stage_key, stage_name) in enumerate(pairs):
            prompt_path = Path(output_dir) / 'prompts' / f'{name}.prompt.md'
            response_path = Path(output_dir) / 'responses' / f'{name}.response.md'
            if prompt_path.exists():
                messages.append({
                    'role': f'{role} Prompt',
                    'sender': f'{role} Prompt',
                    'content': prompt_path.read_text(encoding='utf-8'),
                    'timestamp': '',
                    'sequence': base_sequence + index * 2,
                    'source': 'text_langgraph_prompt',
                    'stage_key': stage_key,
                    'stage_name': stage_name,
                    'io_type': 'input',
                    'title': f'{stage_name}输入',
                })
            if response_path.exists():
                messages.append({
                    'role': role,
                    'sender': role,
                    'content': response_path.read_text(encoding='utf-8'),
                    'timestamp': '',
                    'sequence': base_sequence + index * 2 + 1,
                    'source': 'text_langgraph_response',
                    'stage_key': stage_key,
                    'stage_name': stage_name,
                    'io_type': 'output',
                    'title': f'{stage_name}输出',
                })
        return messages

    def _read_langgraph_testcase_messages(output_dir, base_sequence=10000):
        messages = []
        if not output_dir:
            return messages
        testcase_dir = Path(output_dir) / 'testcase_pipeline'
        pairs = [
            ('04a_prd_block_builder', 'PRD Block Builder', '02_block_prd', 'PRD分块'),
            ('04b_prd_knowledge_builder', 'PRD Knowledge Builder', '03_build_knowledge', '知识构建'),
        ]
        for index, (name, role, stage_key, stage_name) in enumerate(pairs):
            prompt_path = testcase_dir / 'prompts' / f'{name}.prompt.md'
            response_path = testcase_dir / 'responses' / f'{name}.response.md'
            if prompt_path.exists():
                messages.append({
                    'role': f'{role} Prompt',
                    'sender': f'{role} Prompt',
                    'content': prompt_path.read_text(encoding='utf-8'),
                    'timestamp': '',
                    'sequence': base_sequence + index * 2,
                    'source': 'langgraph_testcase_prompt',
                    'stage_key': stage_key,
                    'stage_name': stage_name,
                    'io_type': 'input',
                    'title': f'{stage_name}输入',
                })
            if response_path.exists():
                messages.append({
                    'role': role,
                    'sender': role,
                    'content': response_path.read_text(encoding='utf-8'),
                    'timestamp': '',
                    'sequence': base_sequence + index * 2 + 1,
                    'source': 'langgraph_testcase_response',
                    'stage_key': stage_key,
                    'stage_name': stage_name,
                    'io_type': 'output',
                    'title': f'{stage_name}输出',
                })

        prompt_dir = testcase_dir / 'prompts' / 'test_cases'
        response_dir = testcase_dir / 'responses' / 'test_cases'
        for offset, prompt_path in enumerate(sorted(prompt_dir.glob('*.prompt.md')) if prompt_dir.exists() else []):
            unit_id = prompt_path.name.replace('.prompt.md', '')
            response_path = response_dir / f'{unit_id}.response.md'
            role = 'IntegrationTestCaseWriter' if unit_id.startswith('INT') else 'ModuleTestCaseWriter'
            stage_name = '生成测试用例'
            title_prefix = '链路用例' if unit_id.startswith('INT') else '模块用例'
            messages.append({
                'role': f'{role} Prompt',
                'sender': f'{role} Prompt',
                'content': prompt_path.read_text(encoding='utf-8'),
                'timestamp': '',
                'sequence': base_sequence + 100 + offset * 2,
                'source': 'langgraph_testcase_prompt',
                'unit_id': unit_id,
                'stage_key': '05_generate_unit_cases',
                'stage_name': stage_name,
                'io_type': 'input',
                'title': f'{title_prefix}输入',
            })
            if response_path.exists():
                messages.append({
                    'role': role,
                    'sender': role,
                    'content': response_path.read_text(encoding='utf-8'),
                    'timestamp': '',
                    'sequence': base_sequence + 100 + offset * 2 + 1,
                    'source': 'langgraph_testcase_response',
                    'unit_id': unit_id,
                    'stage_key': '05_generate_unit_cases',
                    'stage_name': stage_name,
                    'io_type': 'output',
                    'title': f'{title_prefix}输出',
                })
        return messages

    def _load_langgraph_nodes(output_dir):
        if not output_dir:
            return {}

        def collect_nodes(base_dir):
            nodes_dir = Path(base_dir) / 'nodes'
            nodes = []
            if not nodes_dir.exists():
                return nodes
            for file_path in sorted(nodes_dir.glob('*.result.json')):
                data = _read_json_file(file_path, default={}) or {}
                input_state = data.get('input_state') or {}
                output_state = data.get('output_state') or {}
                nodes.append({
                    'id': data.get('node') or file_path.stem.replace('.result', ''),
                    'status': data.get('status') or 'unknown',
                    'started_at': data.get('started_at'),
                    'finished_at': data.get('finished_at'),
                    'duration_ms': data.get('duration_ms'),
                    'current_node': output_state.get('current_node') or input_state.get('current_node'),
                    'error': data.get('error'),
                    'path': str(file_path),
                })
            return nodes

        main_state = _read_json_file(Path(output_dir) / 'graph_state.json', default={}) or {}
        testcase_dir = Path(output_dir) / 'testcase_pipeline'
        testcase_state = _read_json_file(testcase_dir / 'graph_state.json', default={}) or {}
        usage_summary = _read_json_file(Path(output_dir) / 'usage' / 'llm_usage_summary.json', default={}) or {}
        return {
            'output_dir': str(output_dir),
            'main_state': main_state,
            'main_nodes': collect_nodes(output_dir),
            'testcase_state': testcase_state,
            'testcase_nodes': collect_nodes(testcase_dir),
            'usage_summary': usage_summary,
        }

    @app.route('/api/tasks', methods=['GET'])
    def list_tasks():
        """列出任务"""
        try:
            limit = request.args.get('limit', default=20, type=int)
            offset = request.args.get('offset', default=0, type=int)
            tasks = task_manager.list_tasks(limit=limit, offset=offset)
            return success_response({'tasks': tasks})
        except Exception as e:
            logger.error(f"获取任务列表失败: {str(e)}")
            return error_response(f"获取任务列表失败: {str(e)}")

    @app.route('/api/tasks/<task_id>', methods=['GET'])
    def get_task(task_id):
        """获取任务详情（统一支持文本PRD和图片任务）"""
        try:
            requested_task_id = task_id
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            # 判断任务类型
            # 1. 如果task_id以img_task_或req_mod_开头，说明是图片任务
            if identity.is_image:
                # 图片任务 - 从RequirementModule表查询
                from database.models import RequirementModule, db_manager
                session = db_manager.get_session()
                try:
                    # 根据task_id或id查询
                    module = session.query(RequirementModule).filter_by(id=identity.module_id).first()

                    if not module:
                        return error_response('任务不存在', 404)

                    # 构建图片任务的详情数据
                    task = {
                        'id': module.task_id or module.generated_task_id or module.id,
                        'module_id': module.id,
                        'requested_id': requested_task_id,
                        'name': module.name,
                        'status': module.status,
                        'processing_stage': module.processing_stage,
                        'progress': module.progress or 0,
                        'message': module.error_message or '',
                        'task_type': 'image_pipeline',
                        'created_at': module.created_at.isoformat() if module.created_at else None,
                        'updated_at': module.updated_at.isoformat() if module.updated_at else None,

                        # 图片任务特有字段
                        'image_count': module.image_count,
                        'image_directory': module.image_directory,
                        'images': module.images or [],  # JSON类型，已自动转换
                        'notes_requirement': module.notes_requirement,
                        'notes_testing': module.notes_testing,
                        'notes': module.notes or {},  # JSON类型，已自动转换

                        # PRD相关
                        'module_analyses': json.loads(module.module_analyses) if module.module_analyses else {},  # Text类型，需要解析
                        'prd_version_content': module.prd_version_content,
                        'prd_final': module.prd_final_content,
                        'prd_file_path': module.prd_file_path,

                        # 确认相关
                        'confirmation_items': json.loads(module.confirmation_questions) if module.confirmation_questions else [],  # Text类型，需要解析
                        'confirmation_answers': json.loads(module.confirmation_answers) if module.confirmation_answers else {},  # Text类型，需要解析

                        # 测试相关
                        'test_analysis': module.test_analysis,
                        'test_cases_raw': module.test_cases_raw,
                        'test_cases': json.loads(module.test_cases_json) if module.test_cases_json else [],  # Text类型，需要解析
                        'test_cases_file_path': module.test_cases_file_path,

                        # 错误信息
                        'error_stage': module.error_stage,
                        'error_message': module.error_message,
                    }

                    return success_response(task)

                finally:
                    session.close()

            else:
                # 2. 文本PRD任务 - 从Task表查询
                task = task_manager.get_task(task_id)

                if not task:
                    return error_response('任务不存在', 404)

                if requested_task_id != task_id:
                    task['requested_id'] = requested_task_id

                # 判断是否为图片任务（通过prd_id判断）
                prd_id = task.get('prd_id', '')
                if prd_id.startswith('req_mod_'):
                    # 图片任务 - 从RequirementModule表获取详细数据
                    from database.models import RequirementModule, db_manager
                    session = db_manager.get_session()
                    try:
                        module = session.query(RequirementModule).filter_by(id=prd_id).first()
                        if module:
                            # 合并图片任务的详细数据
                            task['confirmation_items'] = json.loads(module.confirmation_questions or '[]')
                            task['test_analysis'] = module.test_analysis
                            task['test_cases_raw'] = module.test_cases_raw
                            task['test_cases'] = json.loads(module.test_cases_json or '[]')
                            task['prd_final'] = module.prd_final_content
                            task['task_type'] = 'image_pipeline'

                            # 添加图片任务特有字段
                            task['module_analyses'] = json.loads(module.module_analyses or '{}')
                            task['prd_version_content'] = module.prd_version_content
                            task['confirmation_answers'] = json.loads(module.confirmation_answers or '[]')
                    finally:
                        session.close()
                else:
                    # 文本PRD任务
                    task['task_type'] = 'text_prd'
                    text_langgraph_results = _load_text_langgraph_test_results(task)
                    if text_langgraph_results:
                        testcases = (
                            text_langgraph_results.get('testcases_list')
                            or text_langgraph_results.get('testcases')
                            or text_langgraph_results.get('test_cases')
                            or text_langgraph_results.get('results')
                            or []
                        )
                        if isinstance(testcases, str):
                            try:
                                testcases = json.loads(testcases)
                            except Exception:
                                testcases = []
                        task['testcases'] = testcases if isinstance(testcases, list) else []
                        if not task.get('test_analysis'):
                            task['test_analysis'] = text_langgraph_results.get('test_analysis', '')
                        result_files = task.get('result_files') or {}
                        if isinstance(result_files, str):
                            try:
                                result_files = json.loads(result_files)
                            except Exception:
                                result_files = {}
                        if isinstance(result_files, dict):
                            if not result_files.get('test_results_path'):
                                output_dir = _resolve_text_langgraph_output_dir(task)
                                if output_dir:
                                    candidate = output_dir / 'testcase_pipeline' / 'test_results.json'
                                    if candidate.exists():
                                        result_files['test_results_path'] = str(candidate)
                            if text_langgraph_results.get('artifact_dir') and not result_files.get('artifact_dir'):
                                result_files['artifact_dir'] = text_langgraph_results.get('artifact_dir')
                            if text_langgraph_results.get('artifact_index') and not result_files.get('artifact_index'):
                                result_files['artifact_index'] = text_langgraph_results.get('artifact_index')
                            task['result_files'] = result_files
                        elif task.get('result_files'):
                            result_files = task.get('result_files')
                            if isinstance(result_files, str):
                                try:
                                    result_files = json.loads(result_files)
                                except Exception:
                                    result_files = {}
                            if isinstance(result_files, dict):
                                output_dir = _resolve_text_langgraph_output_dir(task)
                                if output_dir and not result_files.get('test_results_path'):
                                    candidate = output_dir / 'testcase_pipeline' / 'test_results.json'
                                    if candidate.exists():
                                        result_files['test_results_path'] = str(candidate)
                                task['result_files'] = result_files

                return success_response(task)

        except Exception as e:
            logger.error(f"获取任务详情失败: {str(e)}", exc_info=True)
            return error_response(f"获取任务详情失败: {str(e)}")

    @app.route('/api/tasks/<task_id>/brief_status', methods=['GET'])
    def get_task_brief_status(task_id):
        """获取任务轻量级状态 - 优化轮询"""
        try:
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            # 判断任务类型
            if identity.is_image:
                # 图片任务 - 从RequirementModule表查询
                from database.models import RequirementModule, db_manager
                session = db_manager.get_session()
                try:
                    module = session.query(RequirementModule).filter_by(id=identity.module_id).first()

                    if not module:
                        return error_response('任务不存在', 404)

                    has_confirmation_questions = bool(
                        module.confirmation_questions and module.confirmation_questions.strip() not in ['', '[]', 'null']
                    )
                    has_confirmation_answers = bool(
                        module.confirmation_answers and module.confirmation_answers.strip() not in ['', '[]', 'null']
                    )
                    has_pending_confirmation_items = has_confirmation_questions and not has_confirmation_answers
                    needs_confirmation = module.status == 'waiting_confirmation' or has_pending_confirmation_items

                    # 构建状态数据
                    status = {
                        'status': module.status,
                        'completion_percentage': module.progress or 0,
                        'needs_confirmation': needs_confirmation,
                        'has_confirmation_items': has_pending_confirmation_items,
                        'has_pending_confirmation_items': has_pending_confirmation_items,
                        'has_submitted_confirmation': has_confirmation_answers,
                        'updated_at': module.updated_at.isoformat() if module.updated_at else '',
                        'message': module.error_message or '',
                        'processing_stage': module.processing_stage,
                    }

                finally:
                    session.close()
            else:
                # 文本PRD任务
                status = task_manager.get_brief_status(task_id)
                if not status:
                    return error_response('任务不存在', 404)

            # 添加ETag和Cache-Control头
            response = jsonify({
                'success': True,
                'status': status
            })
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['ETag'] = f"W/\"{status.get('updated_at', '')}\""
            return response
        except Exception as e:
            logger.error(f"获取任务状态失败: {str(e)}")
            return error_response(f"获取任务状态失败: {str(e)}")

    @app.route('/api/tasks/<task_id>/messages', methods=['GET'])
    def get_task_messages(task_id):
        """获取任务消息历史（统一支持文本PRD和图片任务）"""
        try:
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            limit = request.args.get('limit', default=100, type=int)

            # 判断是否为图片任务
            is_image_task = identity.is_image

            if is_image_task:
                # 图片任务 - 从日志文件读取AI消息
                module = _get_image_module_by_task_id(task_id)

                # 获取日志目录
                messages = []
                log_root = Path(os.environ.get('LOG_DIR', 'logs')) / 'tasks'
                candidate_task_ids = [task_id]
                if module:
                    candidate_task_ids.extend([
                        module.task_id,
                        module.generated_task_id,
                        f'lg_{module.id}',
                    ])
                seen_task_ids = []
                for candidate in candidate_task_ids:
                    if candidate and candidate not in seen_task_ids:
                        seen_task_ids.append(candidate)

                for candidate in seen_task_ids:
                    messages.extend(_read_ai_response_messages(
                        log_root / 'image_pipeline' / candidate / 'ai_responses',
                        'image_pipeline',
                    ))
                    messages.extend(_read_ai_response_messages(
                        log_root / 'langgraph_image_pipeline' / candidate / 'ai_responses',
                        'langgraph_image_pipeline',
                    ))

                output_dir = _resolve_langgraph_output_dir(module)
                messages.extend(_read_langgraph_testcase_messages(output_dir, base_sequence=20000))
                messages.sort(key=lambda item: (
                    item.get('timestamp') or '',
                    item.get('sequence', 0),
                ))
                if limit and len(messages) > limit:
                    messages = messages[-limit:]

                return success_response({'messages': messages})
            else:
                # 文本PRD任务 - 使用原有逻辑，并兼容新版用例生成流水线调试消息。
                task = task_manager.get_task(task_id)
                if _is_text_langgraph_task(task):
                    output_dir = _resolve_text_langgraph_output_dir(task)
                    messages = []
                    messages.extend(_read_text_langgraph_messages(output_dir, base_sequence=0))
                    messages.extend(_read_langgraph_testcase_messages(output_dir, base_sequence=10000))
                else:
                    # 🔒 旧文本PRD协作消息仍受 AI协作开关控制；LangGraph 调试消息不走旧协作开关。
                    from app_config import SHOW_AI_COLLABORATION
                    if not SHOW_AI_COLLABORATION:
                        return success_response({
                            'messages': [],
                            'disabled': True,
                            'reason': 'AI协作模块已在生产环境中禁用'
                        })
                    messages = task_manager.get_task_messages(task_id, limit=limit)
                    structured_messages = _extract_structured_pipeline_messages(task)
                    if structured_messages:
                        messages = messages + structured_messages

                # 对不同类型的消息进行选择性截断
                processed_messages = []
                for msg in messages:
                    processed_msg = msg.copy()

                    # 获取消息的角色/发送者
                    role = (msg.get('role') or msg.get('sender', '')).lower()
                    content = msg.get('content', '')

                    # 判断是否是AI协作讨论阶段的消息
                    is_ai_collaboration = (
                        role in ['product_manager', 'test_architect'] and
                        not _contains_test_analysis_keywords(content)
                    )

                    # AI协作讨论消息截断到500字，测试分析等其他消息保持完整
                    if is_ai_collaboration and len(content) > 500:
                        processed_msg['content'] = content[:500] + "..."
                        processed_msg['is_truncated'] = True
                    else:
                        processed_msg['is_truncated'] = False

                    processed_messages.append(processed_msg)

                return success_response({'messages': processed_messages})
        except Exception as e:
            logger.error(f"获取任务消息失败: {str(e)}")
            return error_response(f"获取任务消息失败: {str(e)}")

    @app.route('/api/tasks/<task_id>/langgraph', methods=['GET'])
    def get_task_langgraph(task_id):
        """获取 LangGraph 主图和用例子图运行节点。"""
        try:
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            if not identity.is_image:
                task = task_manager.get_task(task_id)
                if not task or not _is_text_langgraph_task(task):
                    return success_response({
                        'enabled': False,
                        'message': '当前任务不是 LangGraph 任务',
                        'main_nodes': [],
                        'testcase_nodes': [],
                    })
                output_dir = _resolve_text_langgraph_output_dir(task)
                if not output_dir:
                    return success_response({
                        'enabled': False,
                        'message': '未找到 LangGraph 运行产物',
                        'main_nodes': [],
                        'testcase_nodes': [],
                    })
                data = _load_langgraph_nodes(output_dir)
                data.update({
                    'enabled': True,
                    'task_id': task_id,
                    'module_id': task.get('prd_id'),
                    'module_name': task.get('name'),
                })
                return success_response(data)

            module = _get_image_module_by_task_id(task_id)
            if not module:
                return error_response('任务不存在', 404)
            output_dir = _resolve_langgraph_output_dir(module)
            if not output_dir:
                return success_response({
                    'enabled': False,
                    'message': '未找到 LangGraph 运行产物',
                    'main_nodes': [],
                    'testcase_nodes': [],
                })
            data = _load_langgraph_nodes(output_dir)
            data.update({
                'enabled': True,
                'task_id': module.task_id or module.generated_task_id,
                'module_id': module.id,
                'module_name': module.name,
            })
            return success_response(data)
        except Exception as e:
            logger.error(f"获取LangGraph运行图失败: {str(e)}", exc_info=True)
            return error_response(f"获取LangGraph运行图失败: {str(e)}")

    def _extract_structured_pipeline_messages(task):
        """Dev only: expose structured testcase prompt/response rounds via AI collaboration."""
        if not task:
            return []
        raw_messages = task.get('test_case_writer_messages') or '[]'
        try:
            if isinstance(raw_messages, str):
                parsed_messages = json.loads(raw_messages)
            else:
                parsed_messages = raw_messages or []
        except Exception as exc:
            logger.warning(f"解析新版用例生成调试消息失败: {exc}")
            return []
        if not isinstance(parsed_messages, list):
            return []

        structured_messages = []
        base_timestamp = task.get('updated_at') or ''
        for index, msg in enumerate(parsed_messages):
            if not isinstance(msg, dict):
                continue
            role = msg.get('role') or ''
            content = msg.get('content') or ''
            if not content:
                continue
            agent_role = _infer_structured_agent_role(content, role, index)
            timestamp = msg.get('timestamp') or msg.get('created_at') or base_timestamp
            structured_messages.append({
                'role': agent_role,
                'sender': agent_role,
                'content': content,
                'timestamp': timestamp,
                'sequence': index,
                'agent_type': agent_role,
                'source': 'structured_testcase_pipeline'
            })
        return structured_messages

    def _infer_structured_agent_role(content, role, index):
        """Map internal structured messages to display-only debug roles."""
        if role == 'user':
            if '【局部需求文档】' in content:
                return 'ModuleTestCaseWriter Prompt'
            if '【用例生成上下文】' in content or '【当前 LU 与关联 BLOCK】' in content:
                return 'PRD Knowledge Context Prompt'
            return 'Structured Pipeline Prompt'
        if 'local_requirement_doc_md' in content:
            return 'PRD Knowledge Context'
        return 'ModuleTestCaseWriter'

    def _contains_test_analysis_keywords(content):
        """检查内容是否包含测试分析关键词"""
        test_analysis_keywords = [
            '测试用例生成完成',
            '【测试用例生成完成】',
            '功能模块识别',
            '测试覆盖策略',
            '模块复杂度评估'
        ]
        return any(keyword in content for keyword in test_analysis_keywords)

    @app.route('/api/tasks/<task_id>/logs', methods=['GET'])
    def get_task_logs(task_id):
        """获取任务日志（统一支持文本PRD和图片任务）"""
        try:
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            limit = request.args.get('limit', default=100, type=int)

            # 判断是否为图片任务
            if identity.is_image:
                # 图片任务 - 从日志文件读取
                import os
                log_ids = [identity.module_task_id, identity.module_id, f'lg_{identity.module_id}']
                log_files = [
                    os.path.join(os.environ.get('LOG_DIR', 'logs'), 'tasks', 'image_pipeline', log_id, 'task.log')
                    for log_id in log_ids
                    if log_id
                ]

                logs = []
                for log_file in log_files:
                    if not os.path.exists(log_file):
                        continue
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            # 只返回最后limit行
                            for line in lines[-limit:]:
                                logs.append({
                                    'message': line.strip(),
                                    'level': 'INFO',
                                    'timestamp': ''
                                })
                    except Exception as e:
                        logger.warning(f"读取日志文件失败: {e}")

                return success_response({'logs': logs})
            else:
                # 文本PRD任务
                logs = task_manager.get_task_logs(task_id, limit=limit)
                return success_response({'logs': logs})

        except Exception as e:
            logger.error(f"获取任务日志失败: {str(e)}")
            return error_response(f"获取任务日志失败: {str(e)}")

    @app.route('/api/tasks/<task_id>/confirmation_items', methods=['GET'])
    def get_task_confirmation_items(task_id):
        """获取任务确认项（统一支持文本PRD和图片任务）"""
        try:
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            # 判断是否为图片任务
            is_image_task = identity.is_image

            logger.info(f"获取确认项: task_id={task_id}, is_image_task={is_image_task}")

            if is_image_task:
                # 图片任务 - 从RequirementModule表获取
                from database.models import RequirementModule, db_manager

                session = db_manager.get_session()
                try:
                    module = session.query(RequirementModule).filter_by(id=identity.module_id).first()

                    if not module:
                        logger.warning(f"未找到RequirementModule: {task_id}")
                        return success_response({'items': []})

                    logger.info(f"找到module: {module.id}, has_questions={bool(module.confirmation_questions)}")

                    if module.confirmation_questions:
                        questions = json.loads(module.confirmation_questions)
                        answers = json.loads(module.confirmation_answers or '{}')  # 字典，不是列表
                        logger.info(f"解析成功: {len(questions)}个问题, {len(answers)}个答案")

                        # 合并问题和答案
                        items = []
                        for i, q in enumerate(questions):
                            question_number = q.get('number', '')
                            answer = answers.get(question_number) if answers else None

                            # 智能处理描述：如果description是"未提供描述"或为空，则使用标题作为描述
                            description = q.get('description', '')
                            if description in ['未提供描述', '未提供', '', None]:
                                # 使用标题作为描述
                                description = q.get('title', '')

                            # 构造question_details字段（Markdown格式）
                            question_details = f"**{q.get('title', '')}**\n\n"

                            # 添加关联功能（如果存在）
                            related_function = q.get('related_function', '')
                            if related_function:
                                question_details += f"**关联功能：** {related_function}\n\n"

                            # 添加问题说明/描述
                            question_details += f"{description}"

                            # 添加参考示例（开放式格式）或选项（选择式格式）
                            options = q.get('options', [])
                            format_type = q.get('format_type', 'choice')
                            reference_examples = q.get('reference_examples') or (options if format_type == 'open' else [])
                            confirm_points = [] if format_type == 'open' else options
                            if options:
                                if format_type == 'open':
                                    question_details += "\n\n**参考示例：**\n"
                                    for opt in options:
                                        question_details += f"- {opt}\n"
                                else:
                                    question_details += "\n\n**选项：**\n"
                                    for idx, opt in enumerate(options, 1):
                                        question_details += f"{idx}. {opt}\n"

                            items.append({
                                'id': i,
                                'question': q.get('title', ''),  # 问题标题
                                'description': description,  # 智能问题描述
                                'options': [] if format_type == 'open' else options,  # 选项数组（用于表单显示）
                                'reference_examples': reference_examples,  # 参考示例（开放式问题）
                                'confirm_points': confirm_points,  # 选择式确认点（旧格式兼容）
                                'format_type': format_type,
                                'question_details': question_details,  # 前端期望的组合字段（Markdown格式）
                                'user_answer': answer,  # 用户答案（API兼容字段）
                                'answer': answer,  # 答案（前端期望字段）
                                'is_submitted': answer is not None
                            })

                        logger.info(f"成功构造{len(items)}个确认项")
                        return success_response({'items': items})
                    else:
                        logger.info("confirmation_questions为空")
                        return success_response({'items': []})
                finally:
                    session.close()
            else:
                # 文本PRD任务 - 使用原有逻辑
                logger.info(f"使用文本PRD逻辑获取确认项")
                items = task_manager.get_confirmation_items(task_id)
                return success_response({'items': items})
        except Exception as e:
            logger.error(f"获取确认项失败: {type(e).__name__}: {str(e)}", exc_info=True)
            return error_response(f"获取确认项失败: {str(e)}")

    @app.route('/api/tasks/<task_id>/results', methods=['GET'])
    def get_task_results(task_id):
        """获取任务结果（统一支持文本PRD和图片任务）"""
        try:
            identity = resolve_task_identity(task_id)
            task_id = identity.canonical_id
            from database.models import RequirementModule, db_manager

            # 1. 如果task_id以req_mod_开头，直接是图片任务的module_id
            # 2. 如果task_id以img_task_开头，需要查找对应的module
            # 3. 否则是文本PRD任务

            if identity.is_image:
                # 直接是图片任务的module_id
                session = db_manager.get_session()
                try:
                    module = session.query(RequirementModule).filter_by(id=identity.module_id).first()
                    if module and module.test_cases_json:
                        results = json.loads(module.test_cases_json)
                        return success_response({'results': results})
                    else:
                        return success_response({'results': [], 'message': '暂无结果'})
                finally:
                    session.close()
            else:
                # 文本PRD任务 - 使用原有逻辑
                results = task_manager.get_task_results(task_id)
                task = task_manager.get_task(task_id)
                text_langgraph_results = _load_text_langgraph_test_results(task)
                if not results:
                    results = (
                        text_langgraph_results.get('testcases_list')
                        or text_langgraph_results.get('testcases')
                        or text_langgraph_results.get('test_cases')
                        or text_langgraph_results.get('results')
                        or (task.get('testcases') if task else [])
                        or []
                    )
                if not results:
                    return success_response({'results': [], 'message': '暂无结果'})

                # 兼容历史数据：如果results是字符串，需要再次解析
                if isinstance(results, str):
                    try:
                        results = json.loads(results)
                    except json.JSONDecodeError:
                        logger.error(f"无法解析测试用例JSON字符串: {task_id}")
                        return error_response("测试用例数据格式错误")

                return success_response({'results': results})
        except Exception as e:
            logger.error(f"获取任务结果失败: {str(e)}")
            return error_response(f"获取任务结果失败: {str(e)}")

    @app.route('/api/tasks/<task_id>/final_prd', methods=['GET'])
    def get_task_final_prd(task_id):
        """获取任务最终PRD"""
        try:
            identity = resolve_task_identity(task_id)
            if identity.is_image:
                from database.models import RequirementModule, db_manager
                session = db_manager.get_session()
                try:
                    module = session.query(RequirementModule).filter_by(id=identity.module_id).first()
                    if not module:
                        return error_response('任务不存在', 404)
                    final_prd = module.prd_final_content or module.prd_version_content or ''
                    if not final_prd:
                        return success_response({'final_prd': '', 'message': '最终PRD尚未生成'})
                    return success_response({'final_prd': final_prd})
                finally:
                    session.close()

            task_id = identity.task_id or task_id
            task = task_manager.get_task(task_id)
            if not task:
                return error_response('任务不存在', 404)

            final_prd = task.get('final_prd', '')
            if not final_prd:
                return success_response({'final_prd': '', 'message': '最终PRD尚未生成'})

            return success_response({'final_prd': final_prd})
        except Exception as e:
            logger.error(f"获取最终PRD失败: {str(e)}")
            return error_response(f"获取最终PRD失败: {str(e)}")

    @app.route('/api/tasks/<task_id>', methods=['DELETE'])
    def delete_task(task_id):
        """删除任务"""
        try:
            success = task_manager.delete_task(task_id)
            if success:
                return success_response({'message': f'任务 {task_id} 删除成功'})
            else:
                return error_response('删除任务失败', 400)
        except Exception as e:
            logger.error(f"删除任务失败: {str(e)}")
            return error_response(f"删除任务失败: {str(e)}")

    @app.route('/api/tasks/delete_by_name', methods=['POST'])
    def delete_tasks_by_name():
        """根据任务名称删除所有匹配的任务"""
        try:
            data = request.get_json()
            task_name = data.get('name')

            if not task_name:
                return error_response('任务名称不能为空', 400)

            deleted_count = task_manager.delete_tasks_by_name(task_name)
            return success_response({
                'message': f'成功删除了 {deleted_count} 个名称为 "{task_name}" 的任务',
                'deleted_count': deleted_count
            })
        except Exception as e:
            logger.error(f"批量删除任务失败: {str(e)}")
            return error_response(f"批量删除任务失败: {str(e)}")

    # 注意: /api/tasks/<task_id>/start 路由已在 routes/generation.py 中定义
    # 避免重复定义导致路由冲突

    app.register_blueprint(tasks_bp, url_prefix='/api/tasks')
