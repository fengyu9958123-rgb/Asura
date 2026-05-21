"""
数据库初始化和管理工具
提供数据库创建、迁移、备份等功能
"""

import os
import json
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from database.models import db_manager, PRD, Task, TaskLog, TaskMessage, TaskStatus
from database.task_manager import safe_get_task_status

class DatabaseInitializer:
    """数据库初始化工具"""

    SAMPLE_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_social_post_interaction_v1.json"
    SAMPLE_ARTIFACTS_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_social_post_interaction_v1_artifacts"
    SAMPLE_PRD_ID = "5d753c2e-131f-48d4-bb95-a7ef30184f91"
    SAMPLE_TASK_ID = "5d753c2e-131f-48d4-bb95-a7ef30184f91_2da2c3e5-128c-49d1-8235-0a5cfad5cc03"
    SAMPLE_TASK_NAME = "社交发帖互动 v1.0"
    
    @staticmethod
    def init_database():
        """初始化数据库"""
        try:
            # 初始化数据库连接
            db_manager.initialize()
            
            print("✅ 数据库初始化成功")
            print(f"📁 数据库文件: data/autogen.db")
            
            # 创建示例数据
            DatabaseInitializer.create_sample_data()
            
            return True
        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            return False
    
    @staticmethod
    def create_sample_data():
        """从真实任务 fixture 创建开源演示数据。"""
        session = db_manager.get_session()
        
        try:
            existing_task = session.query(Task).filter_by(id=DatabaseInitializer.SAMPLE_TASK_ID).first()
            existing_prd = session.query(PRD).filter_by(id=DatabaseInitializer.SAMPLE_PRD_ID).first()
            if existing_task and existing_prd:
                DatabaseInitializer._ensure_sample_task_langgraph_metadata(existing_task)
                session.commit()
                DatabaseInitializer._copy_sample_langgraph_artifacts()
                print("📄 示例任务已存在，已校验 LangGraph 演示产物")
                return

            fixture = DatabaseInitializer._load_sample_fixture()
            sample_prd = DatabaseInitializer._build_prd_from_fixture(fixture["prd"])
            sample_task = DatabaseInitializer._build_task_from_fixture(fixture["task"])

            if existing_task:
                DatabaseInitializer._ensure_sample_task_langgraph_metadata(existing_task)
            if not existing_prd:
                session.add(sample_prd)
            if not existing_task:
                session.add(sample_task)
            DatabaseInitializer._add_fixture_rows(
                session=session,
                model=TaskMessage,
                rows=fixture.get("task_messages") or [],
                existing_ids={row.id for row in session.query(TaskMessage.id).filter_by(task_id=DatabaseInitializer.SAMPLE_TASK_ID).all()},
            )
            DatabaseInitializer._add_fixture_rows(
                session=session,
                model=TaskLog,
                rows=fixture.get("task_logs") or [],
                existing_ids={row.id for row in session.query(TaskLog.id).filter_by(task_id=DatabaseInitializer.SAMPLE_TASK_ID).all()},
            )
            session.commit()
            DatabaseInitializer._copy_sample_langgraph_artifacts()

            print("📄 创建示例任务成功：社交发帖互动 v1.0")
            
        except Exception as e:
            session.rollback()
            print(f"❌ 创建示例数据失败: {e}")
        finally:
            session.close()

    @staticmethod
    def ensure_sample_data():
        """幂等创建开源演示数据。"""
        try:
            db_manager.initialize()
            DatabaseInitializer.create_sample_data()
        except Exception as e:
            print(f"❌ 初始化示例数据失败: {e}")

    @staticmethod
    def _load_sample_fixture():
        if not DatabaseInitializer.SAMPLE_FIXTURE_PATH.exists():
            raise FileNotFoundError(f"示例数据文件不存在: {DatabaseInitializer.SAMPLE_FIXTURE_PATH}")
        with open(DatabaseInitializer.SAMPLE_FIXTURE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _build_prd_from_fixture(data):
        return PRD(
            id=data.get("id"),
            name=data.get("name"),
            content=data.get("content") or "",
            file_path=data.get("file_path"),
            status=data.get("status") or "completed",
            mode=data.get("mode") or "普通模式",
            business=data.get("business"),
            description=data.get("description"),
            generated_task_id=data.get("generated_task_id"),
            created_at=DatabaseInitializer._parse_datetime(data.get("created_at")) or datetime.utcnow(),
            updated_at=DatabaseInitializer._parse_datetime(data.get("updated_at")) or datetime.utcnow(),
        )

    @staticmethod
    def _build_task_from_fixture(data):
        return Task(
            id=data.get("id"),
            prd_id=data.get("prd_id"),
            name=data.get("name"),
            status=safe_get_task_status(str(data.get("status") or "completed").lower()),
            completion_percentage=data.get("completion_percentage") or 100,
            message=data.get("message"),
            prd_content=data.get("prd_content"),
            testcases=data.get("testcases"),
            enhanced_prd=data.get("enhanced_prd"),
            final_prd=data.get("final_prd"),
            architect_questions=data.get("architect_questions"),
            confirmation_items=data.get("confirmation_items"),
            confirmation_results=data.get("confirmation_results"),
            result_files=data.get("result_files"),
            test_analysis=data.get("test_analysis"),
            product_manager_messages=data.get("product_manager_messages"),
            test_architect_messages=data.get("test_architect_messages"),
            test_analyst_messages=data.get("test_analyst_messages"),
            test_case_writer_messages=data.get("test_case_writer_messages"),
            current_phase=data.get("current_phase") or "completed",
            mode=data.get("mode") or "普通模式",
            business=data.get("business"),
            created_at=DatabaseInitializer._parse_datetime(data.get("created_at")) or datetime.utcnow(),
            updated_at=DatabaseInitializer._parse_datetime(data.get("updated_at")) or datetime.utcnow(),
        )

    @staticmethod
    def _sample_langgraph_output_dir():
        return Path("outputs") / "text_pipeline_langgraph" / f"task_{DatabaseInitializer.SAMPLE_TASK_ID}"

    @staticmethod
    def _ensure_sample_task_langgraph_metadata(task):
        result_files = task.result_files if isinstance(task.result_files, dict) else {}
        result_files = dict(result_files or {})
        result_files["pipeline"] = "text_langgraph"
        result_files.setdefault(
            "description",
            "开源内置演示数据，来自真实已完成的 LangGraph 文本 PRD 任务；运行产物会在初始化时复制到 outputs 目录。",
        )
        task.result_files = result_files

    @staticmethod
    def _copy_sample_langgraph_artifacts():
        if not DatabaseInitializer.SAMPLE_ARTIFACTS_PATH.exists():
            print(f"⚠️ 示例 LangGraph 产物不存在: {DatabaseInitializer.SAMPLE_ARTIFACTS_PATH}")
            return

        target_dir = DatabaseInitializer._sample_langgraph_output_dir()
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(DatabaseInitializer.SAMPLE_ARTIFACTS_PATH, target_dir, dirs_exist_ok=True)

    @staticmethod
    def _add_fixture_rows(session, model, rows, existing_ids):
        for row in rows:
            row_id = row.get("id")
            if not row_id or row_id in existing_ids:
                continue
            values = dict(row)
            if "timestamp" in values:
                values["timestamp"] = DatabaseInitializer._parse_datetime(values["timestamp"]) or datetime.utcnow()
            session.add(model(**values))
    
    @staticmethod
    def migrate_from_file_storage():
        """从文件存储迁移到数据库"""
        data_path = "data/tasks"
        if not os.path.exists(data_path):
            print("📁 未找到原有文件存储数据")
            return
        
        session = db_manager.get_session()
        migrated_count = 0
        
        try:
            # 遍历所有任务目录
            for task_dir in os.listdir(data_path):
                task_path = os.path.join(data_path, task_dir)
                if not os.path.isdir(task_path):
                    continue
                
                try:
                    # 读取任务元数据
                    metadata_file = os.path.join(task_path, "metadata.json")
                    if not os.path.exists(metadata_file):
                        continue
                    
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    # 检查任务是否已存在
                    existing_task = session.query(Task).filter_by(id=metadata['id']).first()
                    if existing_task:
                        continue
                    
                    # 创建任务记录
                    task = Task(
                        id=metadata['id'],
                        prd_id=metadata.get('prd_id', ''),
                        name=metadata.get('name', ''),
                        status=safe_get_task_status(metadata.get('status', 'created')),
                        completion_percentage=metadata.get('completion_percentage', 0),
                        message=metadata.get('message', ''),
                        created_at=datetime.fromisoformat(metadata.get('created_at', datetime.utcnow().isoformat())),
                        updated_at=datetime.fromisoformat(metadata.get('updated_at', datetime.utcnow().isoformat()))
                    )
                    
                    # 读取PRD内容
                    prd_content_file = os.path.join(task_path, "prd_content.json")
                    if os.path.exists(prd_content_file):
                        with open(prd_content_file, 'r', encoding='utf-8') as f:
                            task.prd_content = json.load(f)
                    
                    # 读取测试用例
                    testcases_file = os.path.join(task_path, "testcases.json")
                    if os.path.exists(testcases_file):
                        with open(testcases_file, 'r', encoding='utf-8') as f:
                            task.testcases = json.load(f)
                    
                    session.add(task)
                    
                    # 迁移日志数据
                    logs_file = os.path.join(task_path, "logs.jsonl")
                    if os.path.exists(logs_file):
                        with open(logs_file, 'r', encoding='utf-8') as f:
                            for line in f:
                                try:
                                    log_data = json.loads(line.strip())
                                    log = TaskLog(
                                        id=str(uuid.uuid4()),
                                        task_id=metadata['id'],
                                        level=log_data.get('level', 'INFO'),
                                        message=log_data.get('message', ''),
                                        timestamp=datetime.fromisoformat(log_data.get('timestamp', datetime.utcnow().isoformat()))
                                    )
                                    session.add(log)
                                except json.JSONDecodeError:
                                    continue
                    
                    # 迁移消息数据
                    messages_file = os.path.join(task_path, "messages.jsonl")
                    if os.path.exists(messages_file):
                        with open(messages_file, 'r', encoding='utf-8') as f:
                            for line in f:
                                try:
                                    msg_data = json.loads(line.strip())
                                    message = TaskMessage(
                                        id=str(uuid.uuid4()),
                                        task_id=metadata['id'],
                                        sender=msg_data.get('sender', 'system'),
                                        content=msg_data.get('content', ''),
                                        timestamp=datetime.fromisoformat(msg_data.get('timestamp', datetime.utcnow().isoformat()))
                                    )
                                    session.add(message)
                                except json.JSONDecodeError:
                                    continue
                    
                    migrated_count += 1
                    
                except Exception as e:
                    print(f"⚠️  迁移任务 {task_dir} 失败: {e}")
                    continue
            
            session.commit()
            print(f"✅ 数据迁移完成，共迁移 {migrated_count} 个任务")
            
            # 备份原始数据
            backup_path = f"data/tasks_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.move(data_path, backup_path)
            print(f"📦 原始数据已备份到: {backup_path}")
            
        except Exception as e:
            session.rollback()
            print(f"❌ 数据迁移失败: {e}")
        finally:
            session.close()
    
    @staticmethod
    def backup_database():
        """备份数据库"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = f"data/autogen_backup_{timestamp}.db"
            
            if os.path.exists("data/autogen.db"):
                shutil.copy2("data/autogen.db", backup_path)
                print(f"📦 数据库备份完成: {backup_path}")
                return backup_path
            else:
                print("❌ 数据库文件不存在")
                return None
        except Exception as e:
            print(f"❌ 备份失败: {e}")
            return None
    
    @staticmethod
    def get_database_stats():
        """获取数据库统计信息"""
        session = db_manager.get_session()
        
        try:
            stats = {
                "prds_count": session.query(PRD).count(),
                "tasks_count": session.query(Task).count(),
                "logs_count": session.query(TaskLog).count(),
                "messages_count": session.query(TaskMessage).count(),
                "completed_tasks": session.query(Task).filter_by(status=TaskStatus.COMPLETED).count(),
                "failed_tasks": session.query(Task).filter_by(status=TaskStatus.FAILED).count(),
            }
            
            print("📊 数据库统计信息:")
            print(f"  - PRD文档: {stats['prds_count']}")
            print(f"  - 任务总数: {stats['tasks_count']}")
            print(f"  - 完成任务: {stats['completed_tasks']}")
            print(f"  - 失败任务: {stats['failed_tasks']}")
            print(f"  - 日志条数: {stats['logs_count']}")
            print(f"  - 消息条数: {stats['messages_count']}")
            
            return stats
            
        except Exception as e:
            print(f"❌ 获取统计信息失败: {e}")
            return None
        finally:
            session.close()

def main():
    """命令行工具主函数"""
    import sys
    
    if len(sys.argv) < 2:
        print("""
数据库管理工具

使用方法:
  python database/init_db.py init      # 初始化数据库
  python database/init_db.py migrate   # 从文件存储迁移
  python database/init_db.py backup    # 备份数据库
  python database/init_db.py stats     # 查看统计信息
        """)
        return
    
    command = sys.argv[1]
    
    if command == "init":
        DatabaseInitializer.init_database()
    elif command == "migrate":
        DatabaseInitializer.migrate_from_file_storage()
    elif command == "backup":
        DatabaseInitializer.backup_database()
    elif command == "stats":
        DatabaseInitializer.get_database_stats()
    else:
        print(f"❌ 未知命令: {command}")

if __name__ == "__main__":
    main()
