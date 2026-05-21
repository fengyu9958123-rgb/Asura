"""
日志服务模块
负责记录系统日志、AI会话和用户操作
"""

import logging
import os
import json
import csv
from datetime import datetime
import re # Added for detailed chat log analysis


class LoggingService:
    """日志服务，负责记录系统日志、AI会话和用户操作"""
    
    def __init__(self):
        """初始化日志服务"""
        self.logger = logging.getLogger(__name__)
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_dir = os.environ.get('LOG_DIR', 'logs')
        self.raw_responses_dir = os.path.join(self.log_dir, "ai_raw_responses")
        
        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.raw_responses_dir, exist_ok=True)
        
        # 创建必要的日志文件路径
        self.session_json_path = os.path.join(
            self.log_dir, 
            f"api_session_{self.session_id}.json"
        )
        
        # 详细对话日志路径 - 这是主要的AI对话记录
        self.detailed_chat_log_path = os.path.join(
            self.log_dir,
            f"ai_detailed_conversation_{self.session_id}.txt"
        )
        
        # 初始化会话数据
        self.session_data = {
            'session_id': self.session_id,
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'events': [],
            'ai_messages': [],
            'user_confirmations': []
        }
        
        # 初始化详细对话日志 - 唯一的文本日志文件
        self.init_detailed_chat_log()
        
        # 记录系统启动事件
        self.log_system_event("服务启动", f"会话{self.session_id}初始化完成")
        
        self.logger.info(f"日志服务初始化完成，会话{self.session_id}")
    
    
    def init_detailed_chat_log(self):
        """初始化详细对话日志"""
        with open(self.detailed_chat_log_path, 'w', encoding='utf-8') as f:
            f.write("=== AutoGen API 详细对话日志 ===\n")
            f.write(f"会话ID: {self.session_id}\n")
            f.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("该日志包含所有系统消息和AI之间的详细对话内容\n")
            f.write("=============================\n\n")
    
    
    def log_system_event(self, event_type, description):
        """记录系统事件"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'description': description
        }
        self.session_data['events'].append(event)
        
        
        self.logger.info(f"[{event_type}] {description}")
        
        # 记录到详细对话日志
        self.log_ai_chat_detail("系统", None, description, event_type)
    
    def log_ai_chat_detail(self, sender, recipient, content, message_type="对话"):
        """记录详细的AI对话内容"""
        timestamp = datetime.now()
        
        try:
            with open(self.detailed_chat_log_path, 'a', encoding='utf-8') as f:
                f.write(f"\n[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] [{message_type}]\n")
                f.write(f"发送者: {sender} -> 接收者: {recipient or '无特定接收者'}\n")
                f.write("=" * 80 + "\n")
                
                # 分析内容，提取有用的元数据
                metadata = self._analyze_ai_content(content)
                if metadata:
                    f.write("元数据:\n")
                    for key, value in metadata.items():
                        f.write(f"- {key}: {value}\n")
                    f.write("\n")
                
                f.write("内容:\n")
                f.write(content + "\n")
                f.write("=" * 80 + "\n\n")
                # 强制刷新缓冲区
                f.flush()
                
            self.logger.debug(f"详细对话记录: {sender} -> {recipient or '无特定接收者'}")
        except Exception as e:
            self.logger.error(f"记录详细对话到文件失败: {e}")
    
    def _analyze_ai_content(self, content):
        """分析AI内容，提取有用的元数据"""
        metadata = {}
        
        # 尝试识别内容类型
        if "<HUMAN_CONFIRM_START>" in content and "<HUMAN_CONFIRM_END>" in content:
            metadata["内容类型"] = "需要人工确认的问题"
            
            # 尝试提取问题数量（去重）
            confirm_sections = content.split("<HUMAN_CONFIRM_START>")
            if len(confirm_sections) > 1:
                # 提取所有问题标题并去重
                unique_titles = set()
                for section in confirm_sections[1:]:  # 跳过第一个空段
                    # 提取问题标题
                    lines = section.split('\n')
                    for line in lines:
                        if line.strip().startswith('问题标题:'):
                            title = line.strip().replace('问题标题:', '').strip()
                            if title:
                                unique_titles.add(title)
                            break
                
                # 如果没有找到标题，则使用原来的简单计数
                if unique_titles:
                    metadata["人工确认问题数"] = len(unique_titles)
                    metadata["问题标题列表"] = list(unique_titles)
                else:
                    metadata["人工确认问题数"] = len(confirm_sections) - 1
        
        # 检测是否包含测试用例表格
        if "| 模块 | 子模块 | 功能点 |" in content or "| 用例编号 | 用例名称 |" in content:
            metadata["内容类型"] = "测试用例表格"
            
            # 尝试估计测试用例数量
            rows = content.split("\n")
            table_rows = [r for r in rows if r.strip().startswith("|") and r.strip().endswith("|")]
            if len(table_rows) > 2:  # 表头 + 分隔行 + 数据行
                metadata["估计测试用例数"] = len(table_rows) - 2
        
        # 检测是否为批量生成
        batch_match = re.search(r'第(\d+)批.*共(\d+)批', content)
        if batch_match:
            metadata["批次信息"] = f"第{batch_match.group(1)}批/共{batch_match.group(2)}批"
        
        return metadata
    
    def log_ai_message(self, agent_name, content, message_type="对话", recipient=None):
        """记录AI消息"""
        timestamp = datetime.now()
        
        # 添加到会话数据
        message = {
            'timestamp': timestamp.isoformat(),
            'agent': agent_name,
            'content': content,
            'type': message_type,
            'recipient': recipient
        }
        self.session_data['ai_messages'].append(message)
        
        self.logger.info(f"AI消息记录: {agent_name} ({message_type}), 长度: {len(content)} 字符")
        
        # 记录详细对话日志
        self.log_ai_chat_detail(agent_name, recipient, content, message_type)
        
        # 立即保存会话数据到JSON
        self.save_log_to_file()
        
        return message
    
    def log_user_confirmation(self, task_id, question_data, user_response):
        """记录用户确认"""
        timestamp = datetime.now()
        
        # 添加到会话数据
        confirmation = {
            'timestamp': timestamp.isoformat(),
            'task_id': task_id,
            'question_id': question_data.get('id', ''),
            'question': question_data.get('question', ''),
            'response': user_response
        }
        self.session_data['user_confirmations'].append(confirmation)
        
        
        self.logger.info(f"用户确认记录: {question_data.get('question', '')[:20]}..., "
                        f"回答: {user_response}, 任务ID: {task_id}")
        return confirmation
    
    def save_ai_raw_response(self, agent_name, response_content):
        """保存AI原始响应"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{agent_name}_{timestamp}.md"
        filepath = os.path.join(self.raw_responses_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(response_content)
        
        self.logger.info(f"保存AI原始响应: {filepath}")
        return filepath
    
    def close_session(self):
        """关闭会话，保存最终日志"""
        self.session_data['end_time'] = datetime.now().isoformat()
        
        # 保存会话JSON
        self.save_log_to_file()
        
        
        self.logger.info(f"会话 {self.session_id} 已关闭并保存")
    
    def save_log_to_file(self):
        """保存日志到文件"""
        with open(self.session_json_path, 'w', encoding='utf-8') as f:
            json.dump(self.session_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"保存会话日志到: {self.session_json_path}")
        return self.session_json_path
