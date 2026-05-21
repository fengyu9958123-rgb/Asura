"""
统一配置管理模块
提供Flask应用和autogen配置
"""

import os
from datetime import datetime

# --- Flask应用基础配置 ---
DEBUG = True
TESTING = False
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG')
CORS_ORIGINS = "*"

# --- AutoGen配置 ---
AUTOGEN_CONFIG_PATH = os.environ.get('AUTOGEN_CONFIG_PATH', 'config/OAI_CONFIG_LIST')

# --- 任务配置 ---
TASK_TIMEOUT = 3600  # 任务超时时间（秒）
TASK_CLEANUP_INTERVAL = 86400  # 任务清理间隔（秒）

# --- 对话轮次配置 ---
MAX_COLLABORATION_TURNS = 2  # 协作轮次
FINAL_GENERATION_TURNS = 1   # 最终生成轮次

# --- 调试配置 ---
DEBUG_MODE = os.environ.get('DEBUG') == 'True'  # 是否显示调试信息
SILENT_MODE = True  # Agent是否静默模式

# --- 功能开关配置 ---
# 开源版本默认展示 AI 协作和 LangGraph 调试信息，便于理解完整生成过程。
SHOW_AI_COLLABORATION = os.environ.get('SHOW_AI_COLLABORATION', 'True').lower() in ['true', '1', 'yes']

# --- 输出目录 ---
OUTPUT_DIRS = {
    'excel': 'outputs/excel',
    'md': 'outputs/md',
    'html': 'outputs/html',
    'raw': 'outputs/raw'
}


def load_config():
    """加载模型 API 配置。"""
    try:
        from services.config.model_config_service import ModelConfigService

        service = ModelConfigService()
        config_list = service.load_config()
        print(f"✅ 已加载API配置：{service.config_path}")
        return config_list
    except Exception as e:
        print(f"⚠️ 加载配置文件失败: {str(e)}")
        return []


def get_resource_path(resource_name, resource_type='data'):
    """获取资源文件路径
    
    Args:
        resource_name: 资源文件名
        resource_type: 资源类型（data、templates等）
        
    Returns:
        str: 资源文件路径
    """
    # 资源目录
    resource_dir = os.path.join(resource_type)
    
    # 如果资源目录不存在，创建它
    if not os.path.exists(resource_dir):
        os.makedirs(resource_dir, exist_ok=True)
    
    # 返回资源文件路径
    return os.path.join(resource_dir, resource_name)


def get_prd_file_path(prd_id=None, uploads_dir='uploads'):
    """获取PRD文件路径
    
    Args:
        prd_id: PRD ID，如果提供则查找对应的文件
        uploads_dir: 上传文件目录
        
    Returns:
        str: PRD文件的路径
    """
    # API模式：如果提供了prd_id，尝试在uploads目录找到对应文件
    if prd_id:
        prd_dir = os.path.join(uploads_dir)
        if os.path.exists(prd_dir):
            for filename in os.listdir(prd_dir):
                if prd_id in filename:
                    return os.path.join(prd_dir, filename)
    
    # 备选方案：当前工作目录查找
    current_prd = os.path.join(os.getcwd(), "prd.md")
    if os.path.exists(current_prd):
        return current_prd
    
    # 最后备选：使用内置模板
    template_prd = os.path.join("data", "templates", "prd.md")
    if os.path.exists(template_prd):
        return template_prd
    
    return None


def get_output_filename(prd_name, task_id=None, output_dir='outputs/excel'):
    """根据PRD名称和任务ID生成输出Excel文件名"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if task_id:
        filename = f"testcases_{prd_name}_{task_id}.xlsx"
    else:
        filename = f"testcases_{prd_name}_{timestamp}.xlsx"
        
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    return os.path.join(output_dir, filename) 
