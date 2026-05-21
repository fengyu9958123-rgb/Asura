#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
数据库升级脚本：为Task表添加test_analysis字段
用于存储TestArchitect的测试分析报告

执行方式:
    python database/add_test_analysis_field.py
"""

import os
import sys
import sqlite3
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def upgrade_database():
    """添加test_analysis字段到tasks表"""
    
    # 数据库路径
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'autogen.db')
    
    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return False
    
    logger.info(f"连接数据库: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'test_analysis' in columns:
            logger.info("✅ test_analysis字段已存在，无需添加")
            return True
        
        # 添加新字段
        logger.info("开始添加test_analysis字段...")
        cursor.execute("""
            ALTER TABLE tasks 
            ADD COLUMN test_analysis TEXT
        """)
        
        conn.commit()
        logger.info("✅ 成功添加test_analysis字段")
        
        # 验证
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'test_analysis' in columns:
            logger.info("✅ 字段添加验证成功")
            return True
        else:
            logger.error("❌ 字段添加验证失败")
            return False
            
    except Exception as e:
        logger.exception(f"❌ 数据库升级失败: {e}")
        return False
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("数据库升级：添加test_analysis字段")
    logger.info("=" * 60)
    
    success = upgrade_database()
    
    if success:
        logger.info("\n✅ 数据库升级成功！")
        logger.info("新字段 test_analysis 已添加到 tasks 表")
        logger.info("用途：存储TestArchitect的测试分析报告")
        logger.info("说明：TestArchitect在提问后，基于完善的PRD进行测试分析与规划")
    else:
        logger.error("\n❌ 数据库升级失败，请检查日志")
        sys.exit(1)

