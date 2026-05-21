"""
数据库迁移：为PRD表添加新字段
"""
import os
import sys
from sqlalchemy import create_engine, text

# 确保项目根目录在sys.path中
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database.models import DatabaseManager

def upgrade():
    """升级数据库：添加新字段"""
    print("=" * 60)
    print("开始迁移：为PRD表添加新字段")
    
    db_manager = DatabaseManager()
    db_manager.initialize()
    engine = db_manager.get_engine()
    
    connection = engine.connect()
    
    try:
        # 检查字段是否已存在
        result = connection.execute(text("PRAGMA table_info(prds)"))
        columns = [row[1] for row in result.fetchall()]
        
        # 添加status字段
        if 'status' not in columns:
            connection.execute(text("ALTER TABLE prds ADD COLUMN status VARCHAR(20) DEFAULT 'draft'"))
            print("✅ 添加字段: status")
        else:
            print("⏭️  字段已存在: status")
        
        # 添加mode字段
        if 'mode' not in columns:
            connection.execute(text("ALTER TABLE prds ADD COLUMN mode VARCHAR(20) DEFAULT '普通模式'"))
            print("✅ 添加字段: mode")
        else:
            print("⏭️  字段已存在: mode")
        
        # 添加business字段
        if 'business' not in columns:
            connection.execute(text("ALTER TABLE prds ADD COLUMN business VARCHAR(100)"))
            print("✅ 添加字段: business")
        else:
            print("⏭️  字段已存在: business")
        
        # 添加description字段
        if 'description' not in columns:
            connection.execute(text("ALTER TABLE prds ADD COLUMN description TEXT"))
            print("✅ 添加字段: description")
        else:
            print("⏭️  字段已存在: description")
        
        # 添加generated_task_id字段
        if 'generated_task_id' not in columns:
            connection.execute(text("ALTER TABLE prds ADD COLUMN generated_task_id VARCHAR(100)"))
            print("✅ 添加字段: generated_task_id")
        else:
            print("⏭️  字段已存在: generated_task_id")
        
        connection.commit()
        print("\n✅ 迁移完成！")
        
        # 验证表结构
        result = connection.execute(text("PRAGMA table_info(prds)"))
        columns = result.fetchall()
        print(f"\n当前表结构（共{len(columns)}个字段）:")
        for col in columns:
            print(f"  - {col[1]}: {col[2]}")
    
    except Exception as e:
        connection.rollback()
        print(f"\n❌ 迁移失败: {str(e)}")
        raise
    finally:
        connection.close()
    
    print("=" * 60)

if __name__ == '__main__':
    upgrade()

