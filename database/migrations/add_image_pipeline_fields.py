#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本：为 RequirementModule 添加图片流程所需字段

迁移内容：
- 处理流程相关字段（task_id, processing_stage, progress）
- 分析结果存储（module_analyses）
- PRD 相关字段（prd_version_content, prd_final_content, prd_file_path）
- 确认问题相关（confirmation_questions, confirmation_answers）
- 测试用例相关（test_analysis, test_cases_raw, test_cases_json, test_cases_file_path）
- 错误信息字段（error_stage）

执行方式：
    python database/migrations/add_image_pipeline_fields.py
"""

import os
import sys
import logging
from sqlalchemy import create_engine, text

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from database.models import Base

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_db_path():
    """获取数据库路径"""
    db_path = os.path.join(project_root, 'data', 'tc_autogen.db')
    return db_path

def backup_database(engine):
    """备份数据库"""
    import shutil
    from datetime import datetime
    
    db_path = get_db_path()
    if not os.path.exists(db_path):
        logger.warning(f"数据库文件不存在，跳过备份: {db_path}")
        return None
    
    backup_dir = os.path.join(project_root, 'data', 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'tc_autogen_backup_{timestamp}.db')
    
    shutil.copy2(db_path, backup_path)
    logger.info(f"✅ 数据库备份成功: {backup_path}")
    return backup_path

def check_column_exists(connection, table_name, column_name):
    """检查列是否存在"""
    result = connection.execute(text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result]
    return column_name in columns

def add_field_if_not_exists(connection, table_name, field_name, field_type, nullable=True):
    """如果字段不存在则添加"""
    if check_column_exists(connection, table_name, field_name):
        logger.info(f"  ⏭️  字段已存在，跳过: {field_name}")
        return False
    
    try:
        # SQLite 的 ALTER TABLE 语法
        null_constraint = "" if nullable else "NOT NULL"
        sql = f"ALTER TABLE {table_name} ADD COLUMN {field_name} {field_type} {null_constraint}"
        connection.execute(text(sql))
        logger.info(f"  ✅ 字段添加成功: {field_name} ({field_type})")
        return True
    except Exception as e:
        logger.error(f"  ❌ 字段添加失败: {field_name}, 错误: {e}")
        raise

def upgrade():
    """执行迁移：添加新字段"""
    logger.info("=" * 80)
    logger.info("开始数据库迁移：添加图片流程字段")
    logger.info("=" * 80)
    
    # 1. 创建数据库引擎
    db_path = get_db_path()
    db_url = f'sqlite:///{db_path}'
    engine = create_engine(db_url, echo=False)
    
    logger.info(f"数据库路径: {db_path}")
    
    # 2. 备份数据库
    backup_path = backup_database(engine)
    
    # 3. 执行迁移
    with engine.begin() as connection:
        logger.info("\n开始添加字段...")
        logger.info("-" * 60)
        
        # ========== 处理流程相关 ==========
        logger.info("\n【1/4】处理流程相关字段:")
        add_field_if_not_exists(connection, 'requirement_modules', 'task_id', 'VARCHAR(200)')
        add_field_if_not_exists(connection, 'requirement_modules', 'processing_stage', 'VARCHAR(50)')
        add_field_if_not_exists(connection, 'requirement_modules', 'progress', 'INTEGER DEFAULT 0')
        
        # ========== 分析结果存储 ==========
        logger.info("\n【2/4】分析和PRD相关字段:")
        add_field_if_not_exists(connection, 'requirement_modules', 'module_analyses', 'TEXT')  # JSON存储
        add_field_if_not_exists(connection, 'requirement_modules', 'prd_version_content', 'TEXT')
        add_field_if_not_exists(connection, 'requirement_modules', 'prd_final_content', 'TEXT')
        add_field_if_not_exists(connection, 'requirement_modules', 'prd_file_path', 'VARCHAR(500)')
        
        # ========== 确认问题相关 ==========
        logger.info("\n【3/4】确认问题相关字段:")
        add_field_if_not_exists(connection, 'requirement_modules', 'confirmation_questions', 'TEXT')  # JSON存储
        add_field_if_not_exists(connection, 'requirement_modules', 'confirmation_answers', 'TEXT')  # JSON存储
        
        # ========== 测试用例相关 ==========
        logger.info("\n【4/4】测试用例相关字段:")
        add_field_if_not_exists(connection, 'requirement_modules', 'test_analysis', 'TEXT')
        add_field_if_not_exists(connection, 'requirement_modules', 'test_cases_raw', 'TEXT')
        add_field_if_not_exists(connection, 'requirement_modules', 'test_cases_json', 'TEXT')  # JSON存储
        add_field_if_not_exists(connection, 'requirement_modules', 'test_cases_file_path', 'VARCHAR(500)')
        
        # ========== 错误信息（error_stage，error_message已存在）==========
        logger.info("\n【补充】错误信息字段:")
        add_field_if_not_exists(connection, 'requirement_modules', 'error_stage', 'VARCHAR(50)')
        
        # ========== 创建索引 ==========
        logger.info("\n【索引】创建task_id索引...")
        try:
            # 检查索引是否已存在
            result = connection.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_requirement_modules_task_id'"
            ))
            if result.fetchone():
                logger.info("  ⏭️  索引已存在，跳过: idx_requirement_modules_task_id")
            else:
                connection.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_requirement_modules_task_id ON requirement_modules(task_id)"
                ))
                logger.info("  ✅ 索引创建成功: idx_requirement_modules_task_id")
        except Exception as e:
            logger.warning(f"  ⚠️  索引创建失败（可能已存在）: {e}")
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ 数据库迁移完成！")
    logger.info("=" * 80)
    
    if backup_path:
        logger.info(f"\n💡 提示：如需回滚，请使用备份文件: {backup_path}")
    
    # 4. 验证迁移结果
    logger.info("\n验证迁移结果...")
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA table_info(requirement_modules)"))
        columns = [row[1] for row in result]
        
        required_fields = [
            'task_id', 'processing_stage', 'progress',
            'module_analyses', 'prd_version_content', 'prd_final_content', 'prd_file_path',
            'confirmation_questions', 'confirmation_answers',
            'test_analysis', 'test_cases_raw', 'test_cases_json', 'test_cases_file_path',
            'error_stage'
        ]
        
        missing_fields = [f for f in required_fields if f not in columns]
        
        if missing_fields:
            logger.error(f"\n❌ 以下字段未成功添加: {missing_fields}")
            return False
        else:
            logger.info("✅ 所有字段验证通过！")
            logger.info(f"✅ requirement_modules 表现有字段数: {len(columns)}")
            return True

def downgrade():
    """
    回滚迁移：删除新增字段
    
    注意：SQLite 不直接支持 DROP COLUMN，需要重建表
    建议使用备份文件恢复
    """
    logger.warning("=" * 80)
    logger.warning("SQLite 不直接支持 DROP COLUMN")
    logger.warning("如需回滚，请使用备份文件恢复数据库")
    logger.warning("=" * 80)
    
    backup_dir = os.path.join(project_root, 'data', 'backups')
    if os.path.exists(backup_dir):
        backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('tc_autogen_backup')])
        if backups:
            latest_backup = backups[-1]
            logger.info(f"\n最新备份文件: {os.path.join(backup_dir, latest_backup)}")
            logger.info("\n回滚步骤:")
            logger.info("1. 停止应用程序")
            logger.info(f"2. 删除当前数据库: data/tc_autogen.db")
            logger.info(f"3. 复制备份文件: cp {os.path.join(backup_dir, latest_backup)} data/tc_autogen.db")
            logger.info("4. 重启应用程序")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据库迁移工具')
    parser.add_argument('action', choices=['upgrade', 'downgrade'], default='upgrade',
                        help='迁移动作: upgrade(添加字段) 或 downgrade(回滚)')
    
    args = parser.parse_args()
    
    try:
        if args.action == 'upgrade':
            success = upgrade()
            sys.exit(0 if success else 1)
        elif args.action == 'downgrade':
            downgrade()
            sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ 迁移失败: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()

