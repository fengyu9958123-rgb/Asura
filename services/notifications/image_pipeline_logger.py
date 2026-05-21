"""
图片流程日志服务
完整记录图片生成测试用例的各个阶段日志、AI响应和性能指标

设计参考: docs/IMAGE_TO_TESTCASE_DETAILED_DESIGN.md Chapter 8
"""

import os
import json
import logging
import traceback
from datetime import datetime
from contextlib import contextmanager
from typing import Dict, Any, Optional
import time

from services.generation.llm_response_cleaner import strip_model_reasoning


def get_log_root() -> str:
    return os.environ.get('LOG_DIR', 'logs')


class ImagePipelineLogger:
    """
    图片流程专用日志器
    
    日志组织结构:
    logs/image_pipeline/module_{id}/
        ├── main.log                      # 主流程日志
        ├── stages/
        │   ├── stage1_analyzing_images.log
        │   ├── stage2_generating_prd.log
        │   ├── ...
        ├── performance.log               # 性能指标
        └── ai_responses/
            ├── 20231028_103045_ImageAnalyst.json
            ├── 20231028_103145_ImageIntegrationAnalyst.json
            └── ...
    """
    
    def __init__(self, module_id: int, task_id: int):
        self.module_id = module_id
        self.task_id = task_id
        
        # 创建日志目录
        self.log_base_dir = os.path.join(get_log_root(), 'image_pipeline', f'module_{module_id}')
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
        self.metrics = {}
    
    def _create_logger(self, name: str, log_file: str) -> logging.Logger:
        """创建一个独立的logger"""
        logger = logging.getLogger(f"image_pipeline_{self.module_id}_{name}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()  # 清除已有handlers
        
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
        logger.propagate = False  # 不传播到父logger
        
        return logger
    
    def _get_stage_logger(self, stage_name: str, stage_label: str) -> logging.Logger:
        """获取或创建阶段logger"""
        if stage_name not in self.stage_loggers:
            log_file = os.path.join(self.stages_dir, f'{stage_name}_{stage_label}.log')
            self.stage_loggers[stage_name] = self._create_logger(f'stage_{stage_name}', log_file)
        
        return self.stage_loggers[stage_name]
    
    # ========== 主流程日志 ==========
    
    def log_pipeline_start(self):
        """记录流程开始"""
        self.main_logger.info("=" * 80)
        self.main_logger.info(f"图片流程启动: module_id={self.module_id}, task_id={self.task_id}")
        self.main_logger.info("=" * 80)
        self.main_logger.info(f"日志目录: {self.log_base_dir}")
        self.main_logger.info("")
    
    def log_pipeline_end(self, success: bool, duration: float):
        """记录流程结束"""
        self.main_logger.info("")
        self.main_logger.info("=" * 80)
        if success:
            self.main_logger.info(f"✅ 图片流程完成: 总耗时 {duration:.2f}s")
        else:
            self.main_logger.error(f"❌ 图片流程失败: 总耗时 {duration:.2f}s")
        self.main_logger.info("=" * 80)
        
        # 输出性能汇总
        self._log_performance_summary()
    
    # ========== 阶段日志 ==========
    
    @contextmanager
    def log_stage(self, stage_name: str, stage_label: str):
        """
        阶段日志上下文管理器
        
        使用示例:
            with logger.log_stage('stage1', '图片分析'):
                # ... 执行阶段1逻辑
                pass
        """
        stage_logger = self._get_stage_logger(stage_name, stage_label)
        
        # 记录开始
        self.main_logger.info(f"\n{'='*60}")
        self.main_logger.info(f"开始阶段: {stage_label} ({stage_name})")
        self.main_logger.info(f"{'='*60}")
        
        stage_logger.info(f"开始执行: {stage_label}")
        
        start_time = time.time()
        
        try:
            yield stage_logger
            
            # 记录成功
            duration = time.time() - start_time
            stage_logger.info(f"✅ {stage_label}完成，耗时 {duration:.2f}s")
            self.main_logger.info(f"✅ {stage_label}完成，耗时 {duration:.2f}s\n")
            
            # 记录性能指标
            self.log_performance_metric(stage_name, duration)
            
        except Exception as e:
            # 记录错误
            duration = time.time() - start_time
            stage_logger.error(f"❌ {stage_label}失败，耗时 {duration:.2f}s")
            stage_logger.error(f"错误: {e}")
            stage_logger.error(traceback.format_exc())
            
            self.main_logger.error(f"❌ {stage_label}失败，耗时 {duration:.2f}s")
            self.main_logger.error(f"错误: {e}\n")
            
            raise  # 重新抛出异常
    
    def log_stage_input(self, stage_name: str, data: Dict[str, Any]):
        """记录阶段输入数据（结构化）"""
        if stage_name in self.stage_loggers:
            stage_logger = self.stage_loggers[stage_name]
            stage_logger.debug("--- 输入数据 ---")
            stage_logger.debug(json.dumps(data, ensure_ascii=False, indent=2))
    
    def log_stage_output(self, stage_name: str, data: Dict[str, Any]):
        """记录阶段输出数据（结构化）"""
        if stage_name in self.stage_loggers:
            stage_logger = self.stage_loggers[stage_name]
            stage_logger.debug("--- 输出数据 ---")
            stage_logger.debug(json.dumps(data, ensure_ascii=False, indent=2))
    
    # ========== AI响应日志 ==========
    
    def save_ai_response(
        self, 
        agent_name: str, 
        prompt: str, 
        response: str, 
        metadata: Optional[Dict] = None
    ):
        """
        保存AI Agent的Prompt和Response
        同时保存 JSON 和 Markdown 两种格式
        
        Args:
            agent_name: Agent名称
            prompt: 发送给Agent的Prompt
            response: Agent返回的响应
            metadata: 额外元数据（如duration, module_name等）
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 保存 JSON 格式
        json_filename = f"{timestamp}_{agent_name}.json"
        json_filepath = os.path.join(self.ai_responses_dir, json_filename)
        
        # 保存 Markdown 格式（方便查看）
        md_filename = f"{timestamp}_{agent_name}.md"
        md_filepath = os.path.join(self.ai_responses_dir, md_filename)
        
        response = strip_model_reasoning(response)

        prompt_length = len(prompt) if prompt else 0
        response_length = len(response) if response else 0
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'agent_name': agent_name,
            'prompt': prompt,
            'response': response,
            'prompt_length': prompt_length,
            'response_length': response_length,
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
        
        self.main_logger.info(f"💾 AI响应已保存: {agent_name} -> {json_filename} + {md_filename}")
    
    # ========== 性能指标 ==========
    
    def log_performance_metric(self, metric_name: str, duration: float):
        """记录性能指标"""
        self.metrics[metric_name] = duration
        self.perf_logger.info(f"{metric_name}: {duration:.2f}s")
    
    def _log_performance_summary(self):
        """输出性能汇总"""
        if not self.metrics:
            return
        
        self.perf_logger.info("\n" + "=" * 60)
        self.perf_logger.info("性能汇总")
        self.perf_logger.info("=" * 60)
        
        total = sum(self.metrics.values())
        
        for name, duration in self.metrics.items():
            percentage = (duration / total * 100) if total > 0 else 0
            self.perf_logger.info(f"{name:30s}: {duration:8.2f}s ({percentage:5.1f}%)")
        
        self.perf_logger.info("-" * 60)
        self.perf_logger.info(f"{'总耗时':30s}: {total:8.2f}s (100.0%)")
        self.perf_logger.info("=" * 60)
    
    # ========== 错误日志 ==========
    
    def log_error(
        self, 
        stage_name: str, 
        error_type: str, 
        error_message: str, 
        stack_trace: Optional[str] = None
    ):
        """记录详细错误信息"""
        self.main_logger.error(f"\n{'!'*60}")
        self.main_logger.error(f"错误发生: {stage_name}")
        self.main_logger.error(f"错误类型: {error_type}")
        self.main_logger.error(f"错误消息: {error_message}")
        if stack_trace:
            self.main_logger.error(f"堆栈跟踪:\n{stack_trace}")
        self.main_logger.error(f"{'!'*60}\n")
        
        # 也记录到对应的stage logger
        if stage_name in self.stage_loggers:
            stage_logger = self.stage_loggers[stage_name]
            stage_logger.error(f"错误类型: {error_type}")
            stage_logger.error(f"错误消息: {error_message}")
            if stack_trace:
                stage_logger.error(f"堆栈跟踪:\n{stack_trace}")
    
    # ========== 调试日志 ==========
    
    def log_debug(self, message: str, stage_name: Optional[str] = None):
        """记录调试信息"""
        if stage_name and stage_name in self.stage_loggers:
            self.stage_loggers[stage_name].debug(message)
        else:
            self.main_logger.debug(message)


# ========== 日志查询工具（可选） ==========

def get_pipeline_logs(module_id: int) -> Dict[str, str]:
    """
    读取指定模块的所有日志
    
    Returns:
        {'main': '...', 'stage1': '...', 'stage2': '...', ...}
    """
    log_base_dir = os.path.join(get_log_root(), 'image_pipeline', f'module_{module_id}')
    
    if not os.path.exists(log_base_dir):
        return {}
    
    logs = {}
    
    # 读取主日志
    main_log = os.path.join(log_base_dir, 'main.log')
    if os.path.exists(main_log):
        with open(main_log, 'r', encoding='utf-8') as f:
            logs['main'] = f.read()
    
    # 读取阶段日志
    stages_dir = os.path.join(log_base_dir, 'stages')
    if os.path.exists(stages_dir):
        for filename in os.listdir(stages_dir):
            if filename.endswith('.log'):
                stage_name = filename.replace('.log', '')
                with open(os.path.join(stages_dir, filename), 'r', encoding='utf-8') as f:
                    logs[stage_name] = f.read()
    
    # 读取性能日志
    perf_log = os.path.join(log_base_dir, 'performance.log')
    if os.path.exists(perf_log):
        with open(perf_log, 'r', encoding='utf-8') as f:
            logs['performance'] = f.read()
    
    return logs


def get_ai_responses(module_id: int, agent_name: Optional[str] = None) -> list:
    """
    读取AI响应记录
    
    Args:
        module_id: 模块ID
        agent_name: 可选，筛选特定Agent的响应
        
    Returns:
        List of AI response dictionaries
    """
    ai_responses_dir = os.path.join(get_log_root(), 'image_pipeline', f'module_{module_id}', 'ai_responses')
    
    if not os.path.exists(ai_responses_dir):
        return []
    
    responses = []
    
    for filename in sorted(os.listdir(ai_responses_dir)):
        if not filename.endswith('.json'):
            continue
        
        # 如果指定了agent_name，进行筛选
        if agent_name and agent_name not in filename:
            continue
        
        with open(os.path.join(ai_responses_dir, filename), 'r', encoding='utf-8') as f:
            data = json.load(f)
            responses.append(data)
    
    return responses
