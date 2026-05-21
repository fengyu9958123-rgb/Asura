import os
import logging

logger = logging.getLogger(__name__)

class Config:
    def __init__(self):
        """初始化默认配置"""
        self.DEBUG = True
        self.UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
        self.MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
        self.ALLOWED_EXTENSIONS = {'md', 'txt', 'pdf', 'docx'}
        
        # 存储路径配置
        self.STORAGE_PATH = 'data/tasks'
        
        # 会话超时设置（秒）
        self.SESSION_TIMEOUT = 3600
        
        # OpenAI API配置
        self.CONFIG_LIST = self.load_config() or []
        
        # 文件保存路径
        self.OUTPUT_PATHS = {
            'excel': 'outputs/excel',
            'md': 'outputs/md',
            'html': 'outputs/html',
            'raw': 'outputs/raw'
        }

    def load_config(self):
        """加载模型 API 配置。"""
        try:
            from services.config.model_config_service import ModelConfigService

            service = ModelConfigService()
            config_list = service.load_config()
            logger.info(f"成功加载配置文件: {service.config_path}")
            return config_list
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return None
    
