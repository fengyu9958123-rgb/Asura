"""
测试用例生成智能体模板定义
"""

from .product_manager import create_product_manager, TEMPLATES as PM_TEMPLATES
from .test_architect import create_test_architect, TEMPLATES as TA_TEMPLATES
from .module_test_writer import create_module_test_case_writer, TEMPLATES as MTW_TEMPLATES
from .integration_test_writer import create_integration_test_case_writer, TEMPLATES as ITW_TEMPLATES
from .prd_block_builder import create_prd_block_builder, TEMPLATES as PBB_TEMPLATES
from .prd_knowledge_builder import create_prd_knowledge_builder, TEMPLATES as PKB_TEMPLATES
from .test_case_quality_reviewer import create_test_case_quality_reviewer, TEMPLATES as TCQR_TEMPLATES
from .image_analyst import create_image_analyst, TEMPLATES as IA_TEMPLATES
from .image_integration_analyst import create_image_integration_analyst, TEMPLATES as IIA_TEMPLATES
from .image_prd_reviewer import create_image_prd_reviewer, TEMPLATES as IPR_TEMPLATES
from .confirmation_integrator import create_confirmation_integrator, TEMPLATES as CI_TEMPLATES
from .text_prd_logic_reviewer import create_text_prd_logic_reviewer, TEMPLATES as TPLR_TEMPLATES
from .text_final_prd_integrator import create_text_final_prd_integrator, TEMPLATES as TFPI_TEMPLATES

__all__ = [
    'create_product_manager', 'PM_TEMPLATES',
    'create_test_architect', 'TA_TEMPLATES',
    'create_module_test_case_writer', 'MTW_TEMPLATES',
    'create_integration_test_case_writer', 'ITW_TEMPLATES',
    'create_prd_block_builder', 'PBB_TEMPLATES',
    'create_prd_knowledge_builder', 'PKB_TEMPLATES',
    'create_test_case_quality_reviewer', 'TCQR_TEMPLATES',
    'create_image_analyst', 'IA_TEMPLATES',
    'create_image_integration_analyst', 'IIA_TEMPLATES',
    'create_image_prd_reviewer', 'IPR_TEMPLATES',
    'create_confirmation_integrator', 'CI_TEMPLATES',
    'create_text_prd_logic_reviewer', 'TPLR_TEMPLATES',
    'create_text_final_prd_integrator', 'TFPI_TEMPLATES'
]
