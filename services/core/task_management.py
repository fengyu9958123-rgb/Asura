"""
任务管理服务 - 负责管理任务的生命周期
使用分层存储：内存缓存 + 文件系统持久化
"""
import os
import json
import uuid
import glob
import logging
from datetime import datetime

class TaskManager:
    """
    任务管理器，提供任务的创建、存储、检索和状态更新功能
    使用分层存储策略：内存缓存 + 文件系统
    """
    
    def __init__(self, storage_path="data/tasks", logger=None):
        """
        初始化任务管理器
        
        Args:
            storage_path: 任务数据存储路径
            logger: 日志记录器实例
        """
        self.tasks = {}  # 内存缓存
        self.storage_path = storage_path
        self.task_locks = {}  # 添加任务锁字典，用于线程安全
        
        # 设置日志记录器
        if logger is None:
            self.logger = logging.getLogger(__name__)
        elif hasattr(logger, 'logger'):
            # 如果传入的是LoggingService实例，获取其内部logger
            self.logger = logger.logger
        else:
            # 否则使用传入的logger
            self.logger = logger
        
        # 确保存储目录存在
        os.makedirs(storage_path, exist_ok=True)
        self.logger.info("任务管理器初始化完成")
    
    def create_task(self, prd_id, prd_name, prd_content=None):
        """
        创建新任务
        
        Args:
            prd_id: PRD文件ID或标识
            prd_name: PRD名称
            prd_content: PRD内容文本
            
        Returns:
            创建的任务对象
        """
        # 生成初始任务ID
        self.logger.info(f"生成初始任务ID: {prd_id}")
            
        # 确保prd_id是简单字符串
        if isinstance(prd_id, dict):
            # 如果prd_id是一个字典对象，只提取id字段
            if 'id' in prd_id:
                prd_id_str = prd_id['id']
            else:
                # 如果没有id字段，直接生成一个随机ID
                prd_id_str = str(uuid.uuid4())
        elif isinstance(prd_id, str):
            # 尝试解析JSON字符串
            try:
                if prd_id.startswith('{') and prd_id.endswith('}'):
                    prd_dict = json.loads(prd_id)
                    if 'id' in prd_dict:
                        prd_id_str = prd_dict['id']
                    else:
                        prd_id_str = str(uuid.uuid4())
                else:
                    prd_id_str = prd_id
            except:
                # 如果解析失败，保留原始ID
                prd_id_str = prd_id
        else:
            # 如果不是字典也不是字符串，转换为字符串
            prd_id_str = str(prd_id)
            
        # 使用UUID生成唯一标识，并添加到PRD ID后
        task_id = f"{prd_id_str}_{uuid.uuid4()}"
        self.logger.info(f"最终任务ID: {task_id}")
            
        # 创建任务对象
        created_at = datetime.now().isoformat()
        task = {
            "id": task_id,
            "prd_id": prd_id,
            "name": prd_name,
            "status": "created",
            "created_at": created_at,
            "updated_at": created_at,
            "completion_percentage": 0,
            "message": "任务已创建",
        }
        
        if prd_content:
            task["prd_content"] = prd_content
            
        # 存入内存缓存
        self.tasks[task_id] = task
        
        # 持久化存储
        self._save_task_metadata(task)
        if prd_content:
            self._save_task_content(task_id, "prd_content", prd_content)
        
        self.logger.info(f"创建任务: {task_id}, PRD名称: {prd_name}")
        return task

    def get_task(self, task_id):
        """
        获取任务详情
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务对象，不存在则返回None
        """
        # 优先从内存缓存获取
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if "prd_content" not in task or not task["prd_content"]:
                # 即使从内存中获取也尝试重新加载PRD内容
                prd_content = self._load_task_content(task_id, "prd_content")
                if prd_content:
                    task["prd_content"] = prd_content
                    self.logger.debug(f"从文件加载PRD内容到缓存任务: {task_id}, 内容长度: {len(str(prd_content))}")
            return task
            
        # 从文件系统加载
        task = self._load_task_metadata(task_id)
        if task:
            # 加载PRD内容
            prd_content = self._load_task_content(task_id, "prd_content")
            if prd_content:
                task["prd_content"] = prd_content
                self.logger.debug(f"加载PRD内容成功: {task_id}, 内容长度: {len(str(prd_content))}")
            else:
                self.logger.warning(f"未能加载PRD内容: {task_id}")
                
                # 尝试从prd_id加载内容
                if "prd_id" in task:
                    prd_id = task["prd_id"]
                    self.logger.info(f"尝试从prd_id加载内容: {prd_id}")
                    try:
                        # 尝试直接从文件读取
                        from pathlib import Path
                        uploads_dir = Path("uploads")
                        for file_path in uploads_dir.glob("*"):
                            if prd_id in file_path.name:
                                self.logger.info(f"找到PRD文件: {file_path}")
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                    task["prd_content"] = content
                                    # 保存到任务内容中
                                    self._save_task_content(task_id, "prd_content", content)
                                    break
                    except Exception as e:
                        self.logger.error(f"从prd_id加载内容失败: {e}")
                
            # 放入内存缓存
                self.tasks[task_id] = task
            
        return task

    def update_task(self, task_id, **updates):
        """
        更新任务属性
        
        Args:
            task_id: 任务ID
            **updates: 要更新的字段和值
            
        Returns:
            更新后的任务对象，失败返回None
        """
        task = self.get_task(task_id)
        if not task:
            self.logger.error(f"更新任务失败: 任务 {task_id} 不存在")
            return None
        
        # 更新任务字段
        for key, value in updates.items():
            task[key] = value
        
        # 总是更新时间戳
        task["updated_at"] = datetime.now().isoformat()
        
        # 持久化变更
        self._save_task_metadata(task)
        
        # 对于大型内容字段，单独存储
        for key in ["prd_content", "enhanced_prd", "testcases"]:
            if key in updates:
                self._save_task_content(task_id, key, updates[key])
            
        return task

    def update_task_status(self, task_id, status, completion_percentage=None, message=None):
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            completion_percentage: 完成百分比(可选)
            message: 状态消息(可选)
            
        Returns:
            更新后的任务，失败返回None
        """
        updates = {"status": status}
        
        if completion_percentage is not None:
            updates["completion_percentage"] = completion_percentage
            
        if message:
            updates["message"] = message
            
        self.logger.info(f"任务状态更新: {task_id}, {status}, 进度: {completion_percentage}%, 消息: {message}")
        return self.update_task(task_id, **updates)
    
    def add_message(self, task_id, sender, content):
        """
        添加对话消息
        
        Args:
            task_id: 任务ID
            sender: 发送者
            content: 消息内容
            
        Returns:
            成功返回True，失败返回False
        """
        task = self.get_task(task_id)
        if not task:
            self.logger.error(f"添加消息失败: 任务 {task_id} 不存在")
            return False
        
        message = {
            "sender": sender,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        # 添加到内存
        if "messages" not in task:
            task["messages"] = []
        task["messages"].append(message)
        
        # 追加写入消息文件
        self._append_to_task_array(task_id, "messages", message)
        return True
    
    def add_log(self, task_id, level, message):
        """
        添加日志
        
        Args:
            task_id: 任务ID
            level: 日志级别
            message: 日志消息
            
        Returns:
            成功返回True，失败返回False
        """
        task = self.get_task(task_id)
        if not task:
            self.logger.error(f"添加日志失败: 任务 {task_id} 不存在")
            return False
        
        log_entry = {
            "level": level,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        
        # 添加到内存
        if "logs" not in task:
            task["logs"] = []
        task["logs"].append(log_entry)
        
        # 追加写入日志文件
        self._append_to_task_array(task_id, "logs", log_entry)
        return True

    def set_confirmation_items(self, task_id, items):
        """
        设置确认项
        
        Args:
            task_id: 任务ID
            items: 确认项列表
            
        Returns:
            成功返回True，失败返回False
        """
        task = self.get_task(task_id)
        if not task:
            self.logger.error(f"设置确认项失败: 任务 {task_id} 不存在")
            return False
            
        task["confirmation_items"] = items
        task["status"] = "waiting_confirmation"
        task["updated_at"] = datetime.now().isoformat()
            
        # 持久化
        self._save_task_metadata(task)
        self._save_task_content(task_id, "confirmation_items", items)
        return True

    def submit_confirmation(self, task_id, answers):
        """
        提交确认回答
        
        Args:
            task_id: 任务ID
            answers: 回答字典
            
        Returns:
            成功返回True，失败返回False
        """
        task = self.get_task(task_id)
        if not task or "confirmation_items" not in task:
            self.logger.error(f"提交确认失败: 任务 {task_id} 不存在或无确认项")
            return False
            
        # 更新确认项答案
        for i, item in enumerate(task["confirmation_items"]):
            if f"answer_{i}" in answers:
                item["answer"] = answers[f"answer_{i}"]
        
        # 更改状态，继续处理
        task["status"] = "processing"
        task["updated_at"] = datetime.now().isoformat()
        
        # 持久化
        self._save_task_metadata(task)
        self._save_task_content(task_id, "confirmation_items", task["confirmation_items"])
        return True
    
    def save_results(self, task_id, testcases, result_files=None):
        """
        保存测试用例结果
        
        Args:
            task_id: 任务ID
            testcases: 生成的测试用例
            result_files: 结果文件路径列表
            
        Returns:
            成功返回True，失败返回False
        """
        task = self.get_task(task_id)
        if not task:
            self.logger.error(f"保存结果失败: 任务 {task_id} 不存在")
            return False
        
        task["testcases"] = testcases
        if result_files:
            task["result_files"] = result_files
        
        task["status"] = "completed"
        task["completion_percentage"] = 100
        task["updated_at"] = datetime.now().isoformat()
        
        # 持久化
        self._save_task_metadata(task)
        self._save_task_content(task_id, "testcases", testcases)
        if result_files:
            self._save_task_content(task_id, "result_files", result_files)
        return True
    
    def list_tasks(self, limit=20, offset=0):
        """
        列出最近任务
        
        Args:
            limit: 返回数量限制
            offset: 起始位置偏移
            
        Returns:
            任务列表，按创建时间倒序
        """
        # 从文件系统列出所有任务元数据
        task_files = glob.glob(f"{self.storage_path}/*/metadata.json")
        tasks = []
        
        for task_file in sorted(task_files, reverse=True)[offset:offset+limit]:
            try:
                with open(task_file, 'r', encoding='utf-8') as f:
                    tasks.append(json.load(f))
            except Exception as e:
                self.logger.error(f"读取任务文件失败: {task_file}, 错误: {e}")
                
        return tasks

    def get_task_messages(self, task_id, limit=100):
        """
        获取任务消息历史
        
        Args:
            task_id: 任务ID
            limit: 返回消息数量限制
            
        Returns:
            消息列表
        """
        return self._load_task_array(task_id, "messages", limit=limit)

    def get_task_logs(self, task_id, limit=100):
        """
        获取任务日志
        
        Args:
            task_id: 任务ID
            limit: 返回日志数量限制
            
        Returns:
            日志列表
        """
        return self._load_task_array(task_id, "logs", limit=limit)

    def get_confirmation_items(self, task_id):
        """
        获取任务确认项
        
        Args:
            task_id: 任务ID
            
        Returns:
            确认项列表（如果已提交，返回确认结果）
        """
        # 首先尝试获取待确认项
        content = self._load_task_content(task_id, "confirmation_items")
        if content and len(content) > 0:
            return content
        
        # 如果没有待确认项，检查是否有已提交的确认结果
        task = self.get_task(task_id)
        if task:
            confirmation_results = task.get('confirmation_results')
            if confirmation_results:
                # 如果confirmation_results是JSON字符串，解析它
                if isinstance(confirmation_results, str):
                    try:
                        import json
                        confirmation_results = json.loads(confirmation_results)
                    except json.JSONDecodeError:
                        print(f"解析confirmation_results失败: {confirmation_results[:100]}")
                        return []
                
                # 将confirmation_results转换为前端期望的格式
                if isinstance(confirmation_results, list):
                    converted_items = []
                    for result in confirmation_results:
                        converted_item = {
                            'id': result.get('confirmation_id', ''),
                            'question': result.get('question_details', ''),
                            'question_details': result.get('question_details', ''),
                            'user_answer': result.get('user_answer', ''),
                            'confirmed': result.get('confirmed', True),
                            'submitted_at': result.get('submitted_at', ''),
                            # 添加标记表示这是已提交的结果
                            'is_submitted': True
                        }
                        converted_items.append(converted_item)
                    return converted_items
        
        return []

    def get_task_results(self, task_id):
        """
        获取任务结果
        
        Args:
            task_id: 任务ID
            
        Returns:
            测试用例结果
        """
        return self._load_task_content(task_id, "testcases")
        
    def get_brief_status(self, task_id):
        """
        获取任务轻量级状态，用于轮询
        
        Args:
            task_id: 任务ID
            
        Returns:
            轻量级状态信息
        """
        task = self.get_task(task_id)
        if not task:
            return None
            
        return {
            "status": task.get("status", "unknown"),
            "completion_percentage": task.get("completion_percentage", 0),
            "needs_confirmation": task.get("status") == "waiting_confirmation",
            "has_confirmation_items": bool(task.get("confirmation_items")),
            "updated_at": task.get("updated_at", ""),
            "message": task.get("message", "")
        }
        
    def clear_inactive_cache(self, max_items=50):
        """
        清理不活跃的缓存项，避免内存过度占用
        
        Args:
            max_items: 内存中保留的最大任务数
        """
        if len(self.tasks) <= max_items:
            return
            
        # 按更新时间排序，保留最近更新的任务
        sorted_tasks = sorted(
            self.tasks.items(), 
            key=lambda x: x[1].get("updated_at", ""),
            reverse=True
        )
        
        # 清除旧任务缓存
        for task_id, _ in sorted_tasks[max_items:]:
            if task_id in self.tasks:
                del self.tasks[task_id]

    def _save_task_metadata(self, task):
        """
        保存任务元数据
        
        Args:
            task: 任务对象
        """
        task_dir = f"{self.storage_path}/{task['id']}"
        os.makedirs(task_dir, exist_ok=True)
        
        # 创建元数据副本，排除大型字段
        metadata = {k: v for k, v in task.items() 
                   if k not in ["prd_content", "enhanced_prd", "testcases", "messages", "logs"]}
        
        try:
            with open(f"{task_dir}/metadata.json", 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存任务元数据失败: {task['id']}, 错误: {e}")

    def _save_task_content(self, task_id, content_type, content):
        """
        单独保存大型内容
        
        Args:
            task_id: 任务ID
            content_type: 内容类型
            content: 内容数据
        """
        task_dir = f"{self.storage_path}/{task_id}"
        os.makedirs(task_dir, exist_ok=True)
        
        try:
            with open(f"{task_dir}/{content_type}.json", 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存任务内容失败: {task_id}, 类型: {content_type}, 错误: {e}")

    def _append_to_task_array(self, task_id, array_name, item):
        """
        追加写入数组内容
        
        Args:
            task_id: 任务ID
            array_name: 数组名称
            item: 要追加的项
        """
        task_dir = f"{self.storage_path}/{task_id}"
        os.makedirs(task_dir, exist_ok=True)
        array_file = f"{task_dir}/{array_name}.jsonl"
        
        try:
            with open(array_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.error(f"追加任务数组失败: {task_id}, 数组: {array_name}, 错误: {e}")

    def _load_task_metadata(self, task_id):
        """
        加载任务元数据
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务元数据，不存在则返回None
        """
        metadata_file = f"{self.storage_path}/{task_id}/metadata.json"
        if not os.path.exists(metadata_file):
            return None
            
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"加载任务元数据失败: {task_id}, 错误: {e}")
            return None

    def _load_task_content(self, task_id, content_type):
        """
        加载任务内容
        
        Args:
            task_id: 任务ID
            content_type: 内容类型
            
        Returns:
            内容数据，不存在则返回None
        """
        content_file = f"{self.storage_path}/{task_id}/{content_type}.json"
        if not os.path.exists(content_file):
            return None
            
        try:
            with open(content_file, 'r', encoding='utf-8') as f:
                content = json.load(f)
                
                # 特殊处理PRD内容，如果是字符串，需要去除引号
                if content_type == "prd_content" and isinstance(content, str):
                    # 去除JSON字符串可能的额外引号
                    self.logger.debug(f"原始PRD内容: {content[:50]}")
                    if content.startswith('"') and content.endswith('"'):
                        content = json.loads(content)
                        self.logger.debug(f"处理后PRD内容: {content[:50]}")
                        
                return content
        except Exception as e:
            self.logger.error(f"加载任务内容失败: {task_id}, 类型: {content_type}, 错误: {e}")
            return None

    def _load_task_array(self, task_id, array_name, limit=None):
        """
        加载数组内容
        
        Args:
            task_id: 任务ID
            array_name: 数组名称
            limit: 返回数量限制
            
        Returns:
            数组内容列表
        """
        array_file = f"{self.storage_path}/{task_id}/{array_name}.jsonl"
        if not os.path.exists(array_file):
            return []
            
        items = []
        try:
            with open(array_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if limit and len(items) >= limit:
                        break
                    items.append(json.loads(line.strip()))
        except Exception as e:
            self.logger.error(f"加载任务数组失败: {task_id}, 数组: {array_name}, 错误: {e}")
            
        return items 