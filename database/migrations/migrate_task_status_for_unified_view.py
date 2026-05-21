"""
数据迁移：为统一任务视图更新现有数据的状态
执行时间：2025-10-27
目的：确保现有的RequirementModule和PRD记录能够在统一任务视图中正确显示
"""
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database.models import DatabaseManager, RequirementModule, PRD, Task
from sqlalchemy import text

def migrate():
    """执行数据迁移"""
    print("="*80)
    print("开始数据迁移：为统一任务视图更新现有数据状态")
    print("="*80)
    
    db_manager = DatabaseManager()
    db_manager.initialize()
    session = db_manager.get_session()
    
    try:
        # 1. 检查并迁移RequirementModule数据
        print("\n【步骤1】检查RequirementModule表...")
        modules = session.query(RequirementModule).all()
        print(f"找到 {len(modules)} 个图片需求模块")
        
        module_updated = 0
        for module in modules:
            old_status = module.status
            
            # 如果status为None或空，设置为draft
            if not module.status:
                module.status = 'draft'
                module_updated += 1
                print(f"  - 模块 {module.id} ({module.name}): 状态从 None 更新为 'draft'")
            
            # 确保时间字段存在
            if not module.created_at:
                module.created_at = datetime.utcnow()
            if not module.updated_at:
                module.updated_at = datetime.utcnow()
        
        session.commit()
        print(f"✅ RequirementModule迁移完成，更新了 {module_updated} 条记录")
        
        # 2. 检查并迁移PRD数据
        print("\n【步骤2】检查PRD表...")
        prds = session.query(PRD).all()
        print(f"找到 {len(prds)} 个文本PRD")
        
        prd_updated = 0
        for prd in prds:
            old_status = prd.status
            
            # 如果status为None或空，设置为draft
            if not prd.status:
                prd.status = 'draft'
                prd_updated += 1
                print(f"  - PRD {prd.id} ({prd.name}): 状态从 None 更新为 'draft'")
            
            # 如果mode为None，设置默认值
            if not prd.mode:
                prd.mode = '普通模式'
            
            # 确保时间字段存在
            if not prd.created_at:
                prd.created_at = datetime.utcnow()
            if not prd.updated_at:
                prd.updated_at = datetime.utcnow()
        
        session.commit()
        print(f"✅ PRD迁移完成，更新了 {prd_updated} 条记录")
        
        # 3. 统计最终状态
        print("\n【步骤3】迁移后统计...")
        
        # RequirementModule状态统计
        module_stats = {}
        for module in session.query(RequirementModule).all():
            status = module.status or 'unknown'
            module_stats[status] = module_stats.get(status, 0) + 1
        
        print("\n图片需求模块状态分布:")
        for status, count in sorted(module_stats.items()):
            print(f"  - {status}: {count}")
        
        # PRD状态统计
        prd_stats = {}
        for prd in session.query(PRD).all():
            status = prd.status or 'unknown'
            prd_stats[status] = prd_stats.get(status, 0) + 1
        
        print("\n文本PRD状态分布:")
        for status, count in sorted(prd_stats.items()):
            print(f"  - {status}: {count}")
        
        # 4. 显示一些示例数据
        print("\n【步骤4】示例数据预览...")
        
        print("\n最近的图片需求模块（最多5个）:")
        recent_modules = session.query(RequirementModule).order_by(RequirementModule.updated_at.desc()).limit(5).all()
        for module in recent_modules:
            print(f"  - {module.name}")
            print(f"    ID: {module.id}")
            print(f"    状态: {module.status}")
            print(f"    图片数: {module.image_count or 0}")
            print(f"    更新时间: {module.updated_at}")
            if module.generated_task_id:
                print(f"    关联任务: {module.generated_task_id}")
            print()
        
        print("\n最近的文本PRD（最多5个）:")
        recent_prds = session.query(PRD).order_by(PRD.updated_at.desc()).limit(5).all()
        for prd in recent_prds:
            print(f"  - {prd.name}")
            print(f"    ID: {prd.id}")
            print(f"    状态: {prd.status}")
            print(f"    模式: {prd.mode}")
            print(f"    更新时间: {prd.updated_at}")
            if prd.generated_task_id:
                print(f"    关联任务: {prd.generated_task_id}")
            print()
        
        print("\n" + "="*80)
        print("✅ 数据迁移完成！")
        print("="*80)
        print("\n现在可以：")
        print("1. 启动应用: python app.py")
        print("2. 访问工作台: http://localhost:5000")
        print("3. 查看统一任务管理页面")
        print()
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ 迁移过程出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()
    
    return True


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)

