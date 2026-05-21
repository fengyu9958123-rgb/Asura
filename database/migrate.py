#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
数据库迁移工具 - 自动检测并执行所有必要的数据库升级
用于部署时自动同步数据库schema
"""

import sqlite3
import os
import sys
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DatabaseMigrator:
    """数据库迁移管理器"""
    
    def __init__(self, db_path='data/autogen.db'):
        """
        初始化迁移器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        
        # 定义所有必需的字段及其类型
        self.required_fields = {
            'id': 'VARCHAR(100)',
            'prd_id': 'VARCHAR(36)',
            'name': 'VARCHAR(255)',
            'status': 'VARCHAR(21)',
            'completion_percentage': 'INTEGER',
            'message': 'TEXT',
            'prd_content': 'JSON',
            'testcases': 'JSON',
            'enhanced_prd': 'JSON',
            'final_prd': 'JSON',
            'architect_questions': 'JSON',
            'confirmation_items': 'JSON',
            'confirmation_results': 'TEXT',
            'result_files': 'JSON',
            'test_analysis': 'TEXT',  # 测试分析报告
            'product_manager_messages': 'TEXT',
            'test_architect_messages': 'TEXT',
            'test_analyst_messages': 'TEXT',  # TestAnalyst消息历史
            'test_case_writer_messages': 'TEXT',
            'current_phase': 'VARCHAR(50)',
            'mode': 'VARCHAR(20)',
            'business': 'VARCHAR(50)',
            'user_id': 'TEXT',
            'created_at': 'DATETIME',
            'updated_at': 'DATETIME',
        }
    
    def connect(self):
        """连接数据库"""
        try:
            if not os.path.exists(self.db_path):
                logger.error(f"❌ 数据库文件不存在: {self.db_path}")
                return False
            
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            logger.info(f"✅ 成功连接数据库: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"❌ 连接数据库失败: {e}")
            return False
    
    def get_existing_fields(self):
        """获取当前表中已存在的字段"""
        try:
            self.cursor.execute("PRAGMA table_info(tasks)")
            columns = self.cursor.fetchall()
            existing_fields = {col[1]: col[2] for col in columns}
            logger.info(f"📊 当前数据库字段数量: {len(existing_fields)}")
            return existing_fields
        except Exception as e:
            logger.error(f"❌ 获取字段信息失败: {e}")
            return {}
    
    def add_missing_fields(self):
        """添加缺失的字段"""
        existing_fields = self.get_existing_fields()
        added_count = 0
        
        for field_name, field_type in self.required_fields.items():
            if field_name not in existing_fields:
                try:
                    logger.info(f"➕ 添加字段: {field_name} ({field_type})")
                    sql = f"ALTER TABLE tasks ADD COLUMN {field_name} {field_type}"
                    self.cursor.execute(sql)
                    self.conn.commit()
                    logger.info(f"✅ 成功添加字段: {field_name}")
                    added_count += 1
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e).lower():
                        logger.debug(f"⏩ 字段已存在: {field_name}")
                    else:
                        logger.error(f"❌ 添加字段失败 {field_name}: {e}")
                        raise
                except Exception as e:
                    logger.error(f"❌ 添加字段失败 {field_name}: {e}")
                    raise
        
        return added_count
    
    def verify_migration(self):
        """验证迁移结果"""
        existing_fields = self.get_existing_fields()
        missing_fields = []
        
        for field_name in self.required_fields.keys():
            if field_name not in existing_fields:
                missing_fields.append(field_name)
        
        if missing_fields:
            logger.error(f"❌ 迁移验证失败，缺失字段: {missing_fields}")
            return False
        else:
            logger.info(f"✅ 迁移验证成功，所有必需字段均存在 (共{len(existing_fields)}个)")
            return True
    
    def get_database_stats(self):
        """获取数据库统计信息"""
        try:
            # 任务总数
            self.cursor.execute('SELECT COUNT(*) FROM tasks')
            task_count = self.cursor.fetchone()[0]
            
            # 最新任务
            self.cursor.execute('SELECT name, status, created_at FROM tasks ORDER BY created_at DESC LIMIT 1')
            latest_task = self.cursor.fetchone()
            
            stats = {
                'task_count': task_count,
                'latest_task': latest_task
            }
            
            return stats
        except Exception as e:
            logger.error(f"❌ 获取统计信息失败: {e}")
            return None
    
    def migrate(self):
        """执行完整的迁移流程"""
        logger.info("="*70)
        logger.info("🔧 开始数据库迁移")
        logger.info("="*70)
        
        # 连接数据库
        if not self.connect():
            return False
        
        try:
            # 添加缺失字段
            added_count = self.add_missing_fields()
            
            if added_count > 0:
                logger.info(f"✨ 本次迁移添加了 {added_count} 个新字段")
            else:
                logger.info("✓ 数据库schema已是最新，无需迁移")
            
            # 验证迁移
            if not self.verify_migration():
                return False
            
            # 输出统计信息
            stats = self.get_database_stats()
            if stats:
                logger.info("\n" + "="*70)
                logger.info("📊 数据库统计")
                logger.info("="*70)
                logger.info(f"任务总数: {stats['task_count']}")
                if stats['latest_task']:
                    logger.info(f"最新任务: {stats['latest_task'][0]} ({stats['latest_task'][1]}) - {stats['latest_task'][2]}")
            
            logger.info("\n" + "="*70)
            logger.info("✅ 数据库迁移完成！")
            logger.info("="*70)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 迁移过程中发生错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            if self.conn:
                self.conn.close()
                logger.info("🔌 数据库连接已关闭")


def main():
    """主函数"""
    # 检查参数
    db_path = 'data/autogen.db'
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    # 执行迁移
    migrator = DatabaseMigrator(db_path)
    success = migrator.migrate()
    
    # 返回退出码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

