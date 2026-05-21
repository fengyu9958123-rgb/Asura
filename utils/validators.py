"""
输入验证工具
提供API参数验证功能
"""

def validate_task_data(data):
    """验证任务创建数据"""
    if not data:
        return {'valid': False, 'message': '请求数据为空'}
        
    if 'prd_content' not in data:
        return {'valid': False, 'message': '缺少PRD内容'}
        
    if 'prd_name' not in data:
        return {'valid': False, 'message': '缺少PRD名称'}
        
    if not data['prd_content'].strip():
        return {'valid': False, 'message': 'PRD内容不能为空'}
        
    return {'valid': True}

def validate_confirmation_data(data):
    """验证确认结果数据"""
    if not data:
        return {'valid': False, 'message': '请求数据为空'}
        
    if 'confirmation_results' not in data:
        return {'valid': False, 'message': '缺少确认结果'}
        
    return {'valid': True} 