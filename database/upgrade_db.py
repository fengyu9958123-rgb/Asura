#!/usr/bin/env python3
"""
数据库升级脚本
用于升级现有数据库以支持新的字段和状态
"""

import os
import sys
import logging
from sqlalchemy import text

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import db_manager, TaskStatus

logger = logging.getLogger(__name__)

def upgrade_database():
    """升级数据库"""
    try:
        # 初始化数据库连接
        db_manager.initialize()
        engine = db_manager.get_engine()
        
        print("开始数据库升级...")
        
        with engine.connect() as conn:
            # 添加新的枚举值
            print("添加新的任务状态...")
            try:
                # SQLite不直接支持ALTER TYPE，但我们的枚举是以字符串形式存储的
                # 所以新的状态值可以直接使用
                pass
            except Exception as e:
                print(f"添加任务状态时发生错误（可能已存在）: {e}")
            
            # 检查并添加新的列
            print("检查并添加新的表列...")
            
            # 获取现有列信息
            result = conn.execute(text("PRAGMA table_info(tasks)"))
            existing_columns = {row[1] for row in result.fetchall()}
            
            # 需要添加的列
            new_columns = [
                ("final_prd", "JSON"),
                ("architect_questions", "JSON")
            ]
            
            for column_name, column_type in new_columns:
                if column_name not in existing_columns:
                    print(f"添加列: {column_name}")
                    try:
                        conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {column_name} {column_type}"))
                        conn.commit()
                    except Exception as e:
                        print(f"添加列 {column_name} 时发生错误: {e}")
                        conn.rollback()
                else:
                    print(f"列 {column_name} 已存在，跳过")
        
        print("数据库升级完成！")
        
    except Exception as e:
        print(f"数据库升级失败: {e}")
        return False
    
    return True

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    success = upgrade_database()
    if success:
        print("✅ 数据库升级成功")
        sys.exit(0)
    else:
        print("❌ 数据库升级失败")
        sys.exit(1)