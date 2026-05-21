#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全工具模块
提供路径安全验证、文件ID验证等安全相关功能
"""

import os
import re
import logging
from functools import wraps
from werkzeug.security import safe_join

logger = logging.getLogger(__name__)

# ==================== 路径安全 ====================

def is_safe_path(base_dir: str, requested_path: str) -> bool:
    """
    检查请求的路径是否在允许的基础目录内
    防止路径遍历攻击（如 ../../etc/passwd）

    Args:
        base_dir: 允许访问的基础目录
        requested_path: 请求的路径（可能包含恶意的 ../ 等）

    Returns:
        bool: 路径是否安全
    """
    try:
        # 🔒 预检查：拒绝包含危险模式的路径
        dangerous_patterns = ['..', '\x00']
        for pattern in dangerous_patterns:
            if pattern in requested_path:
                logger.warning(f"路径包含危险模式 '{pattern}': {repr(requested_path)}")
                return False

        # 🔒 检查反斜杠（Windows路径分隔符）- 在所有平台上都拒绝
        if '\\' in requested_path:
            logger.warning(f"路径包含反斜杠: {repr(requested_path)}")
            return False

        # 获取基础目录的绝对路径
        base_abs = os.path.abspath(base_dir)

        # 使用 safe_join 安全拼接路径（Werkzeug 提供）
        # 如果路径不安全，safe_join 返回 None
        safe_path = safe_join(base_dir, requested_path)

        if safe_path is None:
            logger.warning(f"路径安全检查失败（safe_join返回None）: base={base_dir}, requested={requested_path}")
            return False

        # 获取最终路径的绝对路径
        final_abs = os.path.abspath(safe_path)

        # 确保最终路径在基础目录内
        # 使用 os.path.commonpath 或简单的前缀检查
        if not final_abs.startswith(base_abs + os.sep) and final_abs != base_abs:
            logger.warning(f"路径安全检查失败（路径逃逸）: base={base_abs}, final={final_abs}")
            return False

        return True

    except Exception as e:
        logger.error(f"路径安全检查异常: {str(e)}")
        return False


def get_safe_path(base_dir: str, requested_path: str) -> str:
    """
    获取安全的文件路径，如果路径不安全则返回 None

    Args:
        base_dir: 允许访问的基础目录
        requested_path: 请求的路径

    Returns:
        str: 安全的绝对路径，如果不安全则返回 None
    """
    try:
        # 使用 Werkzeug 的 safe_join
        safe_path = safe_join(base_dir, requested_path)

        if safe_path is None:
            logger.warning(f"获取安全路径失败: base={base_dir}, requested={requested_path}")
            return None

        # 获取绝对路径
        abs_path = os.path.abspath(safe_path)
        base_abs = os.path.abspath(base_dir)

        # 再次验证路径在基础目录内
        if not abs_path.startswith(base_abs + os.sep) and abs_path != base_abs:
            logger.warning(f"路径逃逸检测: {abs_path} 不在 {base_abs} 内")
            return None

        return abs_path

    except Exception as e:
        logger.error(f"获取安全路径异常: {str(e)}")
        return None


# ==================== ID 验证 ====================

# 预编译正则表达式提高性能
UUID_PATTERN = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', re.IGNORECASE)
TASK_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,200}$')
MODULE_ID_PATTERN = re.compile(r'^req_mod_\d{8}_\d{6}$')
IMAGE_ID_PATTERN = re.compile(r'^img_[a-f0-9]{8}$')
FILE_ID_PATTERN = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', re.IGNORECASE)


def is_valid_uuid(value: str) -> bool:
    """
    验证是否为有效的 UUID 格式

    Args:
        value: 要验证的字符串

    Returns:
        bool: 是否为有效 UUID
    """
    if not value or not isinstance(value, str):
        return False
    return bool(UUID_PATTERN.match(value))


def is_valid_task_id(task_id: str) -> bool:
    """
    验证任务ID格式是否有效
    允许：字母、数字、下划线、短横线，长度1-100

    Args:
        task_id: 任务ID

    Returns:
        bool: 是否有效
    """
    if not task_id or not isinstance(task_id, str):
        return False
    return bool(TASK_ID_PATTERN.match(task_id))


def is_valid_module_id(module_id: str) -> bool:
    """
    验证需求模块ID格式是否有效
    格式：req_mod_YYYYMMDD_HHMMSS

    Args:
        module_id: 模块ID

    Returns:
        bool: 是否有效
    """
    if not module_id or not isinstance(module_id, str):
        return False
    return bool(MODULE_ID_PATTERN.match(module_id))


def is_valid_image_id(image_id: str) -> bool:
    """
    验证图片ID格式是否有效
    格式：img_xxxxxxxx（8位十六进制）

    Args:
        image_id: 图片ID

    Returns:
        bool: 是否有效
    """
    if not image_id or not isinstance(image_id, str):
        return False
    return bool(IMAGE_ID_PATTERN.match(image_id))


def is_valid_file_id(file_id: str) -> bool:
    """
    验证文件ID格式是否有效（UUID格式或安全的字符串）

    Args:
        file_id: 文件ID

    Returns:
        bool: 是否有效
    """
    if not file_id or not isinstance(file_id, str):
        return False

    # 检查是否包含危险字符
    dangerous_patterns = ['..', '/', '\\', '\x00', '\n', '\r']
    for pattern in dangerous_patterns:
        if pattern in file_id:
            logger.warning(f"文件ID包含危险字符: {repr(file_id)}")
            return False

    # UUID 格式
    if FILE_ID_PATTERN.match(file_id):
        return True

    # 需求模块ID格式
    if MODULE_ID_PATTERN.match(file_id):
        return True

    # 通用任务ID格式（字母数字下划线短横线）
    if TASK_ID_PATTERN.match(file_id):
        return True

    return False


def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除危险字符

    Args:
        filename: 原始文件名

    Returns:
        str: 清理后的安全文件名
    """
    if not filename:
        return ''

    # 移除路径分隔符和其他危险字符
    dangerous_chars = ['/', '\\', '..', '\x00', '\n', '\r', '<', '>', ':', '"', '|', '?', '*']
    safe_name = filename

    for char in dangerous_chars:
        safe_name = safe_name.replace(char, '_')

    # 移除开头和结尾的空格和点
    safe_name = safe_name.strip(' .')

    # 限制长度
    if len(safe_name) > 255:
        name, ext = os.path.splitext(safe_name)
        safe_name = name[:255-len(ext)] + ext

    return safe_name if safe_name else 'unnamed'


# ==================== 请求验证 ====================

def validate_file_type(file_type: str, allowed_types: list) -> bool:
    """
    验证文件类型是否在允许列表中

    Args:
        file_type: 请求的文件类型
        allowed_types: 允许的类型列表

    Returns:
        bool: 是否允许
    """
    if not file_type or not isinstance(file_type, str):
        return False
    return file_type.lower() in [t.lower() for t in allowed_types]


# ==================== 日志脱敏 ====================

def mask_sensitive_path(path: str) -> str:
    """
    对路径进行脱敏处理，用于日志记录

    Args:
        path: 原始路径

    Returns:
        str: 脱敏后的路径
    """
    if not path:
        return '[empty]'

    # 如果路径看起来像是攻击尝试，完整记录以便审计
    if '..' in path or path.startswith('/etc') or path.startswith('/root'):
        return f'[SUSPICIOUS: {repr(path)}]'

    # 正常路径只显示最后两级
    parts = path.replace('\\', '/').split('/')
    if len(parts) > 2:
        return '.../' + '/'.join(parts[-2:])
    return path
