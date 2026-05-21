"""
服务模块包
包含所有服务组件，经过重组的目录结构
"""

# 定义可从 services 包级别惰性导出的对象。
__all__ = [
    'SimplifiedGenerationService',
    'AgentService',
    'AnalysisService',
    'TestGenerationService',
    'NotificationService',
    'LoggingService',
    'FileService',
    'extract_confirmation_items',
    'generate_confirmation_summary',
    'GenerationService',  # 向后兼容
]

_LAZY_EXPORTS = {
    'SimplifiedGenerationService': ('services.core.generation_service', 'SimplifiedGenerationService'),
    'GenerationService': ('services.core.generation_service', 'SimplifiedGenerationService'),
    'AgentService': ('services.core.agent_service', 'AgentService'),
    'AnalysisService': ('services.analysis.analysis_service', 'AnalysisService'),
    'TestGenerationService': ('services.generation.test_generation_service', 'TestGenerationService'),
    'NotificationService': ('services.notifications.notification_service', 'NotificationService'),
    'LoggingService': ('services.notifications.logging_service', 'LoggingService'),
    'FileService': ('services.storage.file_service', 'FileService'),
    'extract_confirmation_items': ('services.utils.confirmation_utils', 'extract_confirmation_items'),
    'generate_confirmation_summary': ('services.utils.confirmation_utils', 'generate_confirmation_summary'),
}


def __getattr__(name):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'services' has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
