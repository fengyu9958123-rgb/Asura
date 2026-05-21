"""
统一任务日志服务
支持文本PRD和图片流程两种任务类型，提供统一的日志记录接口
"""

import os
import json
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
from contextlib import contextmanager

from services.generation.llm_response_cleaner import strip_model_reasoning


def get_log_root() -> str:
    return os.environ.get('LOG_DIR', 'logs')


class UnifiedTaskLogger:
    """
    统一任务日志器
    支持文本PRD和图片流程两种任务类型
    
    日志组织结构:
    logs/tasks/{task_type}/task_{id}/
        ├── main.log                      # 主流程日志
        ├── stages/
        │   ├── stage1_{name}.log
        │   ├── stage2_{name}.log
        │   └── ...
        ├── performance.json              # 性能指标
        └── ai_responses/
            ├── 20231028_103045_{agent}.json
            └── ...
    """
    
    def __init__(self, task_id: str, task_type: str):
        """
        初始化日志器
        
        Args:
            task_id: 任务ID
            task_type: 任务类型 ('text_prd' 或 'image_pipeline')
        """
        self.task_id = task_id
        self.task_type = task_type
        
        # task_id已经包含"task_"前缀，不需要再加
        self.log_base_dir = os.path.join(
            get_log_root(),
            'tasks',
            task_type,
            task_id  # 直接使用task_id，不再添加task_前缀
        )
        self.stages_dir = os.path.join(self.log_base_dir, 'stages')
        self.ai_responses_dir = os.path.join(self.log_base_dir, 'ai_responses')
        
        for dir_path in [self.log_base_dir, self.stages_dir, self.ai_responses_dir]:
            os.makedirs(dir_path, exist_ok=True)
        
        # 创建日志器
        self.main_logger = self._create_logger('main', os.path.join(self.log_base_dir, 'main.log'))
        self.perf_logger = self._create_logger('performance', os.path.join(self.log_base_dir, 'performance.log'))
        
        # 阶段日志器（延迟创建）
        self.stage_loggers = {}
        
        # 性能指标存储
        self.metrics = {
            'task_id': task_id,
            'type': task_type,
            'stages': {},
            'start_time': None,
            'end_time': None,
            'total_duration_seconds': 0,
            'total_ai_calls': 0,
            'total_tokens': 0,
            'total_prompt_length': 0,
            'total_response_length': 0
        }
    
    def _create_logger(self, name: str, log_file: str) -> logging.Logger:
        """创建一个独立的logger"""
        logger = logging.getLogger(f"unified_task_{self.task_id}_{name}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        
        # 文件handler
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        
        # 格式
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        fh.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.propagate = False
        
        return logger
    
    # ========== 任务级日志 ==========
    
    def log_task_start(self, metadata: Optional[Dict] = None):
        """记录任务开始"""
        self.metrics['start_time'] = datetime.now().isoformat()
        self.main_logger.info(f"[TASK_START] 任务启动: task_id={self.task_id}, type={self.task_type}")
        if metadata:
            self.main_logger.info(f"[TASK_METADATA] {json.dumps(metadata, ensure_ascii=False)}")
    
    def log_task_end(self, status: str = 'success', error: Optional[str] = None):
        """记录任务结束"""
        end_time = datetime.now()
        self.metrics['end_time'] = end_time.isoformat()
        
        # 计算总耗时
        if self.metrics['start_time']:
            start_time = datetime.fromisoformat(self.metrics['start_time'])
            self.metrics['total_duration_seconds'] = (end_time - start_time).total_seconds()
        
        if status == 'success':
            self.main_logger.info(
                f"[TASK_COMPLETE] 任务完成，总耗时{self.metrics['total_duration_seconds']:.2f}秒"
            )
        else:
            self.main_logger.error(f"[TASK_FAILED] 任务失败: {error}")
            if error:
                self.main_logger.error(f"[ERROR_TRACEBACK]\n{traceback.format_exc()}")
        
        # 保存性能指标
        self._save_performance_metrics()
    
    # ========== 阶段级日志 ==========
    
    @contextmanager
    def log_stage(self, stage_number: int, stage_name: str, description: str = ''):
        """
        阶段日志上下文管理器
        
        用法:
            with logger.log_stage(1, 'analyzing_prd', '分析PRD文档'):
                stage_logger = logger.stage_loggers['stage1']
                stage_logger.info('开始分析...')
                # 阶段逻辑
        """
        stage_key = f'stage{stage_number}'
        stage_log_file = os.path.join(
            self.stages_dir, 
            f'{stage_key}_{stage_name}.log'
        )
        
        stage_logger = self._create_logger(stage_key, stage_log_file)
        self.stage_loggers[stage_key] = stage_logger
        
        # 记录阶段开始
        start_time = datetime.now()
        self.main_logger.info(f"[{stage_key.upper()}_START] 开始阶段{stage_number}：{description}")
        stage_logger.info(f"{'='*60}")
        stage_logger.info(f"阶段{stage_number}：{description}")
        stage_logger.info(f"{'='*60}")
        
        self.metrics['stages'][stage_key] = {
            'name': stage_name,
            'description': description,
            'start_time': start_time.isoformat(),
            'status': 'running',
            'ai_calls': 0,
            'total_tokens': 0,
            'total_prompt_length': 0,
            'total_response_length': 0
        }
        
        try:
            yield stage_logger
            
            # 阶段成功
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            self.metrics['stages'][stage_key].update({
                'end_time': end_time.isoformat(),
                'duration_seconds': duration,
                'status': 'success'
            })
            
            self.main_logger.info(f"[{stage_key.upper()}_END] 完成阶段{stage_number}，耗时{duration:.2f}秒")
            stage_logger.info(f"{'='*60}")
            stage_logger.info(f"阶段{stage_number}完成，耗时{duration:.2f}秒")
            stage_logger.info(f"{'='*60}")
            
        except Exception as e:
            # 阶段失败
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            self.metrics['stages'][stage_key].update({
                'end_time': end_time.isoformat(),
                'duration_seconds': duration,
                'status': 'failed',
                'error': str(e)
            })
            
            self.main_logger.error(f"[{stage_key.upper()}_FAILED] 阶段{stage_number}失败: {str(e)}")
            self.main_logger.error(f"[ERROR_TRACEBACK]\n{traceback.format_exc()}")
            stage_logger.error(f"{'='*60}")
            stage_logger.error(f"阶段{stage_number}失败: {str(e)}")
            stage_logger.error(f"[ERROR_TRACEBACK]\n{traceback.format_exc()}")
            stage_logger.error(f"{'='*60}")
            
            raise
    
    # ========== AI响应日志 ==========
    
    def save_ai_response(
        self, 
        agent_name: str, 
        prompt: str, 
        response: str, 
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        保存AI响应（包含请求和响应长度统计）
        同时保存 JSON 和 Markdown 两种格式
        
        Args:
            agent_name: 智能体名称
            prompt: 发送给AI的prompt
            response: AI的响应
            metadata: 其他元数据（tokens, duration, model等）
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:17]  # 精确到毫秒前3位
        
        # 保存 JSON 格式
        json_filename = f"{timestamp}_{agent_name}.json"
        json_filepath = os.path.join(self.ai_responses_dir, json_filename)
        
        # 保存 Markdown 格式（方便查看）
        md_filename = f"{timestamp}_{agent_name}.md"
        md_filepath = os.path.join(self.ai_responses_dir, md_filename)
        
        response = strip_model_reasoning(response)

        # 计算长度
        prompt_length = len(prompt) if prompt else 0
        response_length = len(response) if response else 0
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'agent_name': agent_name,
            'prompt': prompt,
            'prompt_length': prompt_length,  # 关键指标
            'response': response,
            'response_length': response_length,  # 关键指标
            'metadata': metadata or {}
        }
        
        # 保存 JSON 文件
        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 保存 Markdown 文件（方便查看）
        md_content = f"""# {agent_name} AI Response

**时间**: {data['timestamp']}

---

## Prompt ({prompt_length:,} 字符)

```
{prompt}
```

---

## Response ({response_length:,} 字符)

{response}

---

## Metadata

```json
{json.dumps(metadata or {}, ensure_ascii=False, indent=2)}
```
"""
        with open(md_filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        # 更新统计
        self.metrics['total_ai_calls'] += 1
        self.metrics['total_prompt_length'] += prompt_length
        self.metrics['total_response_length'] += response_length
        
        # 提取tokens信息
        if metadata:
            tokens = metadata.get('tokens_used', {})
            if isinstance(tokens, dict):
                total_tokens = tokens.get('total', 0)
            else:
                total_tokens = tokens if isinstance(tokens, (int, float)) else 0
            self.metrics['total_tokens'] += total_tokens
        
        # 更新当前阶段统计
        current_stage = self._get_current_stage()
        if current_stage:
            stage_metrics = self.metrics['stages'].get(current_stage, {})
            stage_metrics['ai_calls'] = stage_metrics.get('ai_calls', 0) + 1
            stage_metrics['total_prompt_length'] = stage_metrics.get('total_prompt_length', 0) + prompt_length
            stage_metrics['total_response_length'] = stage_metrics.get('total_response_length', 0) + response_length
            if metadata:
                tokens = metadata.get('tokens_used', {})
                if isinstance(tokens, dict):
                    total_tokens = tokens.get('total', 0)
                else:
                    total_tokens = tokens if isinstance(tokens, (int, float)) else 0
                stage_metrics['total_tokens'] = stage_metrics.get('total_tokens', 0) + total_tokens
        
        self.main_logger.debug(
            f"[AI_RESPONSE] 保存{agent_name}响应: {json_filename} + {md_filename}, "
            f"prompt_len={prompt_length}, response_len={response_length}"
        )
    
    def _get_current_stage(self) -> Optional[str]:
        """获取当前正在运行的阶段"""
        for stage_key, stage_data in self.metrics['stages'].items():
            if stage_data.get('status') == 'running':
                return stage_key
        return None
    
    # ========== 性能指标 ==========
    
    def log_performance_metric(self, metric_name: str, value: float, unit: str = ''):
        """记录性能指标"""
        self.perf_logger.info(f"{metric_name}: {value} {unit}")
        self.main_logger.debug(f"[PERFORMANCE] {metric_name}: {value} {unit}")
    
    def _save_performance_metrics(self):
        """保存性能指标到JSON文件"""
        filepath = os.path.join(self.log_base_dir, 'performance.json')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.metrics, f, ensure_ascii=False, indent=2)
        
        self.perf_logger.info("="*60)
        self.perf_logger.info("任务性能总结")
        self.perf_logger.info("="*60)
        self.perf_logger.info(json.dumps(self.metrics, ensure_ascii=False, indent=2))
    
    # ========== 输入输出日志 ==========
    
    def log_input(self, stage_key: str, input_type: str, content: str, metadata: Optional[Dict] = None):
        """记录输入数据"""
        stage_logger = self.stage_loggers.get(stage_key)
        if stage_logger:
            stage_logger.info(f"[INPUT] {input_type}: {len(content)} 字符")
            stage_logger.debug(f"[INPUT_CONTENT] {content[:500]}...")  # 只记录前500字符
            if metadata:
                stage_logger.debug(f"[INPUT_METADATA] {json.dumps(metadata, ensure_ascii=False)}")
    
    def log_output(self, stage_key: str, output_type: str, content: str, metadata: Optional[Dict] = None):
        """记录输出数据"""
        stage_logger = self.stage_loggers.get(stage_key)
        if stage_logger:
            stage_logger.info(f"[OUTPUT] {output_type}: {len(content)} 字符")
            stage_logger.debug(f"[OUTPUT_CONTENT] {content[:500]}...")  # 只记录前500字符
            if metadata:
                stage_logger.debug(f"[OUTPUT_METADATA] {json.dumps(metadata, ensure_ascii=False)}")
    
    # ========== 错误日志 ==========
    
    def log_error(self, error_type: str, error_message: str, exception: Optional[Exception] = None):
        """记录错误"""
        self.main_logger.error(f"[ERROR] {error_type}: {error_message}")
        if exception:
            self.main_logger.error(f"[EXCEPTION] {type(exception).__name__}: {str(exception)}")
            self.main_logger.error(f"[TRACEBACK]\n{traceback.format_exc()}")
