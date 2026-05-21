"""
数据库升级脚本：添加test_analyst_messages字段
用于存储TestAnalyst智能体的对话历史
"""

import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def upgrade_database():
    """添加test_analyst_messages字段到tasks表"""
    
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'autogen.db')
    
    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return False
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'test_analyst_messages' not in columns:
            logger.info("开始添加test_analyst_messages字段...")
            cursor.execute("ALTER TABLE tasks ADD COLUMN test_analyst_messages TEXT")
            conn.commit()
            logger.info("✅ 成功添加test_analyst_messages字段")
        else:
            logger.info("test_analyst_messages字段已存在，无需添加")
        
        # 验证字段是否添加成功
        cursor.execute("PRAGMA table_info(tasks)")
        columns_after = [col[1] for col in cursor.fetchall()]
        if 'test_analyst_messages' in columns_after:
            logger.info("✅ 字段添加验证成功")
            return True
        else:
            logger.error("❌ 字段添加验证失败")
            return False
            
    except sqlite3.OperationalError as e:
        logger.error(f"❌ 数据库升级失败: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        logger.error(f"❌ 数据库升级失败: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    logger.info("============================================================")
    logger.info("数据库升级：添加test_analyst_messages字段")
    logger.info("============================================================")
    logger.info(f"连接数据库: {os.path.join(os.path.dirname(__file__), '..', 'data', 'autogen.db')}")
    
    if upgrade_database():
        logger.info("\n✅ 数据库升级成功！")
        logger.info("新字段 test_analyst_messages 已添加到 tasks 表")
        logger.info("用途：存储TestAnalyst（测试分析师）的对话历史")
        logger.info("说明：TestAnalyst专注于测试策略规划，不再与TestArchitect职责混合")
    else:
        logger.error("\n❌ 数据库升级失败，请检查日志")

