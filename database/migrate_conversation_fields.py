#!/usr/bin/env python3
"""
数据库迁移脚本：添加DeepSeek conversation fields到Task表
"""

import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_add_conversation_fields(db_path="data/autogen.db"):
    """为Task表添加对话历史字段"""
    
    if not os.path.exists(db_path):
        logger.info(f"数据库文件不存在: {db_path}，将在应用启动时自动创建")
        return True
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        if not cursor.fetchone():
            logger.info("tasks表不存在，跳过迁移")
            conn.close()
            return True
        
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]
        
        fields_to_add = [
            ('product_manager_messages', 'TEXT'),
            ('test_architect_messages', 'TEXT'), 
            ('test_case_writer_messages', 'TEXT'),
            ('current_phase', 'VARCHAR(50)')
        ]
        
        for field_name, field_type in fields_to_add:
            if field_name not in columns:
                logger.info(f"添加字段: {field_name}")
                cursor.execute(f"ALTER TABLE tasks ADD COLUMN {field_name} {field_type}")
            else:
                logger.info(f"字段已存在: {field_name}")
        
        conn.commit()
        conn.close()
        
        logger.info("数据库迁移完成")
        return True
        
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")
        if 'conn' in locals():
            conn.close()
        return False

if __name__ == "__main__":
    success = migrate_add_conversation_fields()
    if success:
        print("✅ 数据库迁移成功完成")
    else:
        print("❌ 数据库迁移失败")
        exit(1)