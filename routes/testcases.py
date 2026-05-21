"""
测试用例相关API路由
提供测试用例的获取、下载、解析等功能
"""

import os
from flask import Blueprint, request, jsonify, send_file
from utils.task_identity import resolve_task_identity

testcases_bp = Blueprint('testcases', __name__, url_prefix='/api/testcases')


def _resolve_text_task_id(task_id):
    identity = resolve_task_identity(task_id)
    return identity.task_id if identity.is_text and identity.task_id else task_id


@testcases_bp.route('/tasks/<task_id>', methods=['GET'])
def get_test_cases(task_id):
    """获取任务的测试用例
    
    URL参数:
        task_id: 任务ID
        
    返回:
        task_id: 任务ID
        content: 测试用例内容
        raw_response: 测试用例生成消息
        
    错误码:
        404: 任务不存在、测试用例尚未生成
    """
    from app import generation_service
    task_id = _resolve_text_task_id(task_id)
    
    # 检查任务是否存在
    task = generation_service.get_task(task_id)
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        }), 404
    
    # 检查测试用例是否已生成（统一使用testcases字段）
    if not task.get('testcases'):
        return jsonify({
            'success': False,
            'message': '测试用例尚未生成'
        }), 404
    
    return jsonify({
        'success': True,
        'data': {
            'task_id': task_id,
            'content': task.get('testcases'),
            'raw_response': task.get('test_case_writer_messages', ''),
            'is_batch_mode': False,
            'current_batch': 0,
            'total_batches': 1
        }
    })


@testcases_bp.route('/tasks/<task_id>/download', methods=['GET'])
def download_test_cases(task_id):
    """下载测试用例文件
    
    URL参数:
        task_id: 任务ID
        
    查询参数:
        format: 文件格式 (excel|html)，默认excel
        
    返回:
        文件下载流
        
    错误码:
        400: 不支持的文件格式
        404: 任务不存在、测试用例尚未生成
        500: 导出Excel失败、导出HTML失败
    """
    from app import generation_service, file_service
    task_id = _resolve_text_task_id(task_id)
    
    # 检查任务是否存在
    task = generation_service.get_task(task_id)
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        }), 404
    
    # 检查测试用例是否已生成（统一使用testcases字段）
    if not task.get('testcases'):
        return jsonify({
            'success': False,
            'message': '测试用例尚未生成'
        }), 404
    
    # 获取文件格式
    file_format = request.args.get('format', 'excel')
    
    if file_format == 'excel':
        # 保存为Excel
        file_path = file_service.save_test_cases_to_excel(
            task.get('testcases'),
            task.get('prd_name'),
            task_id
        )
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({
                'success': False,
                'message': '导出Excel失败'
            }), 500
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"testcases_{task.get('prd_name')}.xlsx"
        )
    

    elif file_format == 'html':
        # 生成HTML预览
        raw_response = task.get('test_case_writer_messages', '')
        html_path = file_service.save_html_preview(
            raw_response,
            "test_cases",
            task.get('prd_name'),
            task_id
        )
        
        if not html_path or not os.path.exists(html_path):
            return jsonify({
                'success': False,
                'message': '导出HTML失败'
            }), 500
        
        return send_file(
            html_path,
            as_attachment=True,
            download_name=f"testcases_{task.get('prd_name')}.html"
        )
    
    else:
        return jsonify({
            'success': False,
            'message': f'不支持的文件格式: {file_format}'
        }), 400


# 移除无用的API：解析测试用例内容（该功能不必要）
# @testcases_bp.route('/tasks/<task_id>/parse', methods=['POST'])
# def parse_test_cases(task_id):


# 移除无用的API：获取测试覆盖率分析结果（功能不完善）
# @testcases_bp.route('/tasks/<task_id>/coverage', methods=['GET'])
# def get_test_coverage(task_id):


@testcases_bp.route('/tasks/<task_id>/raw', methods=['GET'])
def get_raw_ai_response(task_id):
    """获取智能体的原始回复
    
    URL参数:
        task_id: 任务ID
        
    查询参数:
        agent: 智能体类型 (ModuleTestCaseWriter|ProductManager)，默认ModuleTestCaseWriter
        
    返回:
        文件下载流（.md格式）
        
    错误码:
        404: 任务不存在、测试用例尚未生成、增强版PRD尚未生成
        500: 保存原始回复失败
    """
    from app import generation_service, file_service, logging_service
    task_id = _resolve_text_task_id(task_id)
    
    # 检查任务是否存在
    task = generation_service.get_task(task_id)
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        }), 404
    
    # 获取智能体类型
    agent_type = request.args.get('agent', 'ModuleTestCaseWriter')
    if agent_type == 'TestCaseWriter':
        agent_type = 'ModuleTestCaseWriter'
    
    # 检查测试用例是否已生成（统一使用testcases字段）
    if not task.get('testcases') and agent_type == 'ModuleTestCaseWriter':
        return jsonify({
            'success': False,
            'message': '测试用例尚未生成'
        }), 404
    
    if not task.get('enhanced_prd') and agent_type == 'ProductManager':
        return jsonify({
            'success': False,
            'message': '增强版PRD尚未生成'
        }), 404
    
    # 根据智能体类型获取内容
    content = ''
    if agent_type == 'ModuleTestCaseWriter':
        content = task.get('test_case_writer_messages', '')
    elif agent_type == 'ProductManager':
        content = task.get('enhanced_prd', '')
    
    # 保存原始回复
    file_path = file_service.save_raw_ai_response(
        agent_type,
        content,
        task_id
    )
    
    if not file_path or not os.path.exists(file_path):
        return jsonify({
            'success': False,
            'message': '保存原始回复失败'
        }), 500
    
    logging_service.log_system_event(
        "导出原始回复",
        f"为任务 {task_id} 导出 {agent_type} 的原始回复"
    )
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"{agent_type}_raw_{task_id}.md"
    )
