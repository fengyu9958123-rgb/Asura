"""
修复卡住的任务状态
检查processing状态的PRD，如果关联的Task已完成或失败，更新PRD状态
"""
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database.models import DatabaseManager, PRD, Task, TaskStatus, RequirementModule

def fix_stuck_tasks():
    """修复卡住的任务"""
    print("="*80)
    print("检查并修复卡住的任务状态")
    print("="*80)
    
    db_manager = DatabaseManager()
    db_manager.initialize()
    session = db_manager.get_session()
    
    try:
        # 1. 检查processing状态的PRD
        print("\n【检查文本PRD】")
        processing_prds = session.query(PRD).filter_by(status='processing').all()
        print(f"找到 {len(processing_prds)} 个processing状态的PRD")
        
        for prd in processing_prds:
            print(f"\n  PRD: {prd.name} (ID: {prd.id})")
            print(f"  状态: {prd.status}")
            print(f"  关联任务: {prd.generated_task_id}")
            
            if prd.generated_task_id:
                task = session.query(Task).filter_by(id=prd.generated_task_id).first()
                if task:
                    print(f"  任务状态: {task.status}")
                    
                    # 如果任务已完成，更新PRD状态
                    if task.status == TaskStatus.COMPLETED:
                        prd.status = 'completed'
                        prd.completed_at = task.updated_at
                        print(f"  ✅ 更新PRD状态为 'completed'")
                    
                    # 如果任务失败，更新PRD状态
                    elif task.status == TaskStatus.FAILED:
                        prd.status = 'draft'  # 失败后恢复为draft，可重新编辑
                        print(f"  ✅ 更新PRD状态为 'draft' (任务失败)")
                    
                    # 如果任务等待确认
                    elif task.status == TaskStatus.WAITING_CONFIRMATION:
                        print(f"  ⏳ 任务等待确认，保持processing状态")
                    
                    # 如果任务已取消
                    elif task.status == TaskStatus.CANCELLED:
                        prd.status = 'draft'
                        print(f"  ✅ 更新PRD状态为 'draft' (任务已取消)")
                else:
                    print(f"  ⚠️ 关联任务不存在，更新PRD为draft")
                    prd.status = 'draft'
            else:
                print(f"  ⚠️ 无关联任务，更新PRD为draft")
                prd.status = 'draft'
        
        session.commit()
        
        # 2. 检查processing状态的RequirementModule
        print("\n【检查图片需求模块】")
        processing_modules = session.query(RequirementModule).filter_by(status='processing').all()
        print(f"找到 {len(processing_modules)} 个processing状态的图片需求模块")
        
        for module in processing_modules:
            print(f"\n  模块: {module.name} (ID: {module.id})")
            print(f"  状态: {module.status}")
            print(f"  关联任务: {module.generated_task_id}")
            
            if module.generated_task_id:
                task = session.query(Task).filter_by(id=module.generated_task_id).first()
                if task:
                    print(f"  任务状态: {task.status}")
                    
                    if task.status == TaskStatus.COMPLETED:
                        module.status = 'completed'
                        module.completed_at = task.updated_at
                        print(f"  ✅ 更新模块状态为 'completed'")
                    
                    elif task.status == TaskStatus.FAILED:
                        module.status = 'submitted'  # 失败后恢复为submitted，可重新启动
                        print(f"  ✅ 更新模块状态为 'submitted' (任务失败)")
                    
                    elif task.status == TaskStatus.WAITING_CONFIRMATION:
                        print(f"  ⏳ 任务等待确认，保持processing状态")
                    
                    elif task.status == TaskStatus.CANCELLED:
                        module.status = 'submitted'
                        print(f"  ✅ 更新模块状态为 'submitted' (任务已取消)")
                else:
                    print(f"  ⚠️ 关联任务不存在，更新模块为submitted")
                    module.status = 'submitted'
            else:
                print(f"  ⚠️ 无关联任务，更新模块为submitted")
                module.status = 'submitted'
        
        session.commit()
        
        # 3. 显示修复后的统计
        print("\n" + "="*80)
        print("修复完成！最终状态统计：")
        print("="*80)
        
        print("\n文本PRD状态分布:")
        prd_stats = {}
        for prd in session.query(PRD).all():
            status = prd.status or 'unknown'
            prd_stats[status] = prd_stats.get(status, 0) + 1
        for status, count in sorted(prd_stats.items()):
            print(f"  - {status}: {count}")
        
        print("\n图片需求模块状态分布:")
        module_stats = {}
        for module in session.query(RequirementModule).all():
            status = module.status or 'unknown'
            module_stats[status] = module_stats.get(status, 0) + 1
        for status, count in sorted(module_stats.items()):
            print(f"  - {status}: {count}")
        
        print("\n✅ 所有任务状态已修复！现在可以正常查看了。")
        print()
        
        return True
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ 修复过程出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()


if __name__ == '__main__':
    success = fix_stuck_tasks()
    sys.exit(0 if success else 1)

