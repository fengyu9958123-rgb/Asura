"""
数据库模型定义
简化的SQLite + SQLAlchemy方案，适合测试项目
"""

from datetime import datetime
from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer, Enum, JSON, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import enum

Base = declarative_base()

class TaskStatus(enum.Enum):
    """任务状态枚举"""
    CREATED = "created"
    PROCESSING = "processing"
    RUNNING = "running"
    ANALYZING = "analyzing"
    COLLABORATING = "collaborating"
    PM_RESPONDING = "pm_responding"
    CHECKING_INTERVENTION = "checking_intervention"
    WAITING_CONFIRMATION = "waiting_confirmation"
    FINALIZING_PRD = "finalizing_prd"
    GENERATING = "generating"
    SAVING = "saving"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class PRD(Base):
    """PRD文档模型"""
    __tablename__ = 'prds'
    
    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    file_path = Column(String(512))
    status = Column(String(20), default='draft')  # draft/processing/completed
    mode = Column(String(20), default='普通模式')  # 历史兼容字段，不再参与文本PRD流程
    business = Column(String(100))  # 业务类型
    description = Column(Text)  # 描述说明
    generated_task_id = Column(String(100))  # 关联的任务ID
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 索引优化
    __table_args__ = (
        Index('idx_prd_created_at', 'created_at'),
        Index('idx_prd_name', 'name'),
        Index('idx_prd_status', 'status'),
    )
    
    def to_dict(self):
        """序列化为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'content': self.content,
            'file_path': self.file_path,
            'status': self.status,
            'business': self.business,
            'description': self.description,
            'generated_task_id': self.generated_task_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class Task(Base):
    """任务模型"""
    __tablename__ = 'tasks'
    
    id = Column(String(100), primary_key=True)
    prd_id = Column(String(36), nullable=False)  # 关联PRD
    name = Column(String(255), nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.CREATED)
    completion_percentage = Column(Integer, default=0)
    message = Column(Text)
    
    # JSON字段存储复杂数据
    prd_content = Column(JSON)  # PRD内容快照
    testcases = Column(JSON)    # 生成的测试用例
    enhanced_prd = Column(JSON) # 增强版PRD
    final_prd = Column(JSON)    # 最终完善的PRD
    architect_questions = Column(JSON)  # 测试架构师问题
    confirmation_items = Column(JSON)  # 确认项
    confirmation_results = Column(Text)  # 人工确认结果(JSON格式)
    result_files = Column(JSON)  # 结果文件路径
    test_analysis = Column(Text)  # 测试分析报告（TestArchitect的测试规划）
    
    # DeepSeek对话历史字段
    product_manager_messages = Column(Text)    # ProductManager对话历史
    test_architect_messages = Column(Text)     # TestArchitect对话历史
    test_analyst_messages = Column(Text)       # TestAnalyst对话历史（新增）
    test_case_writer_messages = Column(Text)   # TestCaseWriter对话历史
    current_phase = Column(String(50))         # 当前执行阶段
    mode = Column(String(20), default='普通模式')  # AI工作模式
    business = Column(String(50))               # 业务类型
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 性能优化索引
    __table_args__ = (
        Index('idx_task_status_created', 'status', 'created_at'),
        Index('idx_task_prd_id', 'prd_id'),
        Index('idx_task_updated_at', 'updated_at'),
    )

class TaskLog(Base):
    """任务日志模型"""
    __tablename__ = 'task_logs'
    
    id = Column(String(36), primary_key=True)
    task_id = Column(String(100), nullable=False)
    level = Column(String(20), nullable=False)  # INFO, ERROR, DEBUG
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # 索引优化
    __table_args__ = (
        Index('idx_log_task_time', 'task_id', 'timestamp'),
        Index('idx_log_level', 'level'),
    )

class TaskMessage(Base):
    """任务消息模型"""
    __tablename__ = 'task_messages'
    
    id = Column(String(36), primary_key=True)
    task_id = Column(String(100), nullable=False)
    sender = Column(String(100), nullable=False)  # system, user, ai
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # 索引优化
    __table_args__ = (
        Index('idx_message_task_time', 'task_id', 'timestamp'),
        Index('idx_message_sender', 'sender'),
    )

class RequirementModule(Base):
    """需求模块表 - 图片需求收集"""
    __tablename__ = 'requirement_modules'
    
    # ========== 基本信息 ==========
    id = Column(String(100), primary_key=True, comment='需求模块ID: req_mod_xxx')
    name = Column(String(255), nullable=False, comment='需求大模块名称，如：对讲平台v2.0.6')
    description = Column(Text, comment='模块描述')
    
    # ========== 状态管理 ==========
    status = Column(String(50), default='draft', comment='状态: draft/submitted/processing/completed/failed')
    # draft: 草稿（可编辑）
    # submitted: 已提交（不可编辑，等待生成）
    # processing: 生成中（阶段2）
    # completed: 已完成（阶段2）
    # failed: 生成失败（阶段2）
    
    # ========== 图片信息 ==========
    image_count = Column(Integer, default=0, comment='图片数量')
    image_directory = Column(String(512), comment='图片存储目录')
    images = Column(JSON, comment='图片列表: [{"id": "img_001", "name": "...", "path": "...", "size": 1024, "order": 1}]')
    notes = Column(JSON, comment='图片备注信息: {"filename": {"module": "模块名", "change_type": "新增"}}')
    
    # ========== 备注信息（两类，均可选）==========
    notes_requirement = Column(Text, nullable=True, comment='需求文档补充：背景、功能点等')
    notes_testing = Column(Text, nullable=True, comment='测试补充：测试重点、场景等')
    
    # ========== 流程处理相关（图片生成测试用例流程）==========
    task_id = Column(String(200), comment='关联的任务ID')
    processing_stage = Column(String(50), comment='当前处理阶段: analyzing_images/generating_prd/reviewing_prd/auto_confirming/integrating_confirmations/generating_testcases/saving_results/completed')
    progress = Column(Integer, default=0, comment='进度百分比 0-100')
    
    # ========== 分析结果存储 ==========
    module_analyses = Column(Text, comment='各模块图片分析结果(JSON): {"module_name": {"analysis": "...", "evaluation": "..."}}')
    
    # ========== PRD 相关 ==========
    prd_version_content = Column(Text, comment='版本PRD内容（阶段2生成）')
    prd_final_content = Column(Text, comment='最终确认后的PRD内容（阶段5生成）')
    prd_file_path = Column(String(500), comment='PRD文件路径')
    
    # ========== 确认问题相关 ==========
    confirmation_questions = Column(Text, comment='确认问题列表(JSON): [{"question": "...", "options": [...], "answer_index": 1}]')
    confirmation_answers = Column(Text, comment='用户确认答案(JSON): {"Q001": "选项1", ...}')
    
    # ========== 测试用例相关 ==========
    test_analysis = Column(Text, comment='测试分析内容（TestAnalyst输出）')
    test_cases_raw = Column(Text, comment='原始测试用例Markdown（TestCaseWriter输出）')
    test_cases_json = Column(Text, comment='解析后的测试用例JSON: [{"id": "TC001", "title": "...", ...}]')
    test_cases_file_path = Column(String(500), comment='测试用例文件路径')
    
    # ========== 关联任务（阶段2使用）==========
    generated_task_id = Column(String(100), comment='生成的测试任务ID（旧字段，保留兼容性）')
    generation_result = Column(JSON, comment='生成结果：文件路径等（旧字段，保留兼容性）')
    
    # ========== 错误信息 ==========
    error_message = Column(Text, comment='错误信息')
    error_stage = Column(String(50), comment='出错阶段')
    
    # ========== 时间戳 ==========
    created_at = Column(DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')
    submitted_at = Column(DateTime, comment='提交时间')
    completed_at = Column(DateTime, comment='完成时间')
    
    # 索引
    __table_args__ = (
        Index('idx_req_mod_status_created', 'status', 'created_at'),
        Index('idx_req_mod_name', 'name'),
        Index('idx_req_mod_task_id', 'task_id'),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'image_count': self.image_count,
            'image_directory': self.image_directory,
            'images': self.images or [],
            'notes_requirement': self.notes_requirement,
            'notes_testing': self.notes_testing,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
        }

# 数据库连接管理
class DatabaseManager:
    """数据库管理器 - 单例模式"""
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def initialize(self, database_url="sqlite:///data/autogen.db"):
        """初始化数据库连接"""
        if self._engine is None:
            # 创建数据目录
            import os
            os.makedirs("data", exist_ok=True)
            
            self._engine = create_engine(
                database_url,
                echo=False,  # 生产环境设为False
                pool_pre_ping=True,  # 连接检查
                connect_args={"check_same_thread": False}  # SQLite多线程支持
            )
            
            # 创建所有表
            Base.metadata.create_all(self._engine)
            
            # 运行数据库迁移（添加对话历史字段）
            self._run_conversation_fields_migration()
            
            # 运行数据库迁移（添加确认结果字段）
            self._run_confirmation_results_migration()
            
            # 运行数据库迁移（添加模式字段）
            self._run_mode_field_migration()
            
            # 创建会话工厂
            self._session_factory = sessionmaker(bind=self._engine)
    
    def get_session(self):
        """获取数据库会话"""
        if self._session_factory is None:
            raise RuntimeError("数据库未初始化，请先调用initialize()")
        return self._session_factory()
    
    def get_engine(self):
        """获取数据库引擎"""
        return self._engine
    
    def _run_conversation_fields_migration(self):
        """运行对话历史字段迁移"""
        try:
            import sqlite3
            import os
            
            # 从连接URL中提取数据库路径
            db_path = "data/autogen.db"
            
            if not os.path.exists(db_path):
                # 数据库文件不存在，SQLAlchemy已经创建了正确的表结构
                return
            
            # 连接数据库检查并添加缺失的字段
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
            if not cursor.fetchone():
                conn.close()
                return
            
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
                    cursor.execute(f"ALTER TABLE tasks ADD COLUMN {field_name} {field_type}")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"运行对话字段迁移时出错: {e}")
            # 不影响主要流程，继续执行
    
    def _run_confirmation_results_migration(self):
        """运行确认结果字段迁移"""
        try:
            import sqlite3
            import os
            
            # 从连接URL中提取数据库路径
            db_path = "data/autogen.db"
            
            if not os.path.exists(db_path):
                # 数据库文件不存在，SQLAlchemy已经创建了正确的表结构
                return
            
            # 连接数据库检查并添加缺失的字段
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
            if not cursor.fetchone():
                conn.close()
                return
            
            # 检查confirmation_results字段是否已存在
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'confirmation_results' not in columns:
                cursor.execute("ALTER TABLE tasks ADD COLUMN confirmation_results TEXT")
                print("已添加confirmation_results字段到tasks表")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"运行确认结果字段迁移时出错: {e}")
            # 不影响主要流程，继续执行
    
    def _run_mode_field_migration(self):
        """运行模式字段迁移"""
        try:
            import sqlite3
            import os
            
            # 从连接URL中提取数据库路径
            db_path = "data/autogen.db"
            
            if not os.path.exists(db_path):
                # 数据库文件不存在，SQLAlchemy已经创建了正确的表结构
                return
            
            # 连接数据库检查并添加缺失的字段
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
            if not cursor.fetchone():
                conn.close()
                return
            
            # 检查mode字段是否已存在
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'mode' not in columns:
                cursor.execute("ALTER TABLE tasks ADD COLUMN mode VARCHAR(20) DEFAULT '普通模式'")
                print("已添加mode字段到tasks表")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"运行模式字段迁移时出错: {e}")
            # 不影响主要流程，继续执行

# 全局数据库管理器实例
db_manager = DatabaseManager()
