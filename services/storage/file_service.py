"""
文件服务 - 处理文件的上传、存储和检索
"""

import os
import uuid
import json
import logging
from datetime import datetime
import pandas as pd
from werkzeug.utils import secure_filename

PUBLIC_TEST_CASE_COLUMNS = [
    "功能模块", "测试场景分类", "用例编号", "用例名称", "前置条件",
    "测试步骤", "预期结果", "优先级", "用例类型",
]
HIDDEN_TEST_CASE_COLUMNS = {
    "关联需求", "原始用例编号", "测试包ID", "测试包类型", "测试ID",
}

class FileService:
    """文件服务，处理文件的上传、存储和检索"""
    
    def __init__(self, upload_folder, logging_service=None):
        """
        初始化文件服务
        
        Args:
            upload_folder: 上传文件夹路径
            logging_service: 日志服务实例
        """
        self.upload_folder = upload_folder
        
        # 确保目录存在
        os.makedirs(upload_folder, exist_ok=True)
        
        # 创建各类型文件的子文件夹
        self.outputs_folder = os.path.join(os.path.dirname(upload_folder), "outputs")
        os.makedirs(self.outputs_folder, exist_ok=True)
        
        self.excel_folder = os.path.join(self.outputs_folder, "excel")
        os.makedirs(self.excel_folder, exist_ok=True)
        
        self.html_folder = os.path.join(self.outputs_folder, "html")
        os.makedirs(self.html_folder, exist_ok=True)
        
        self.md_folder = os.path.join(self.outputs_folder, "md")
        os.makedirs(self.md_folder, exist_ok=True)
        
        self.raw_folder = os.path.join(self.outputs_folder, "raw")
        os.makedirs(self.raw_folder, exist_ok=True)
        
        # 设置日志
        if logging_service:
            self.logging_service = logging_service
            self.logger = logging.getLogger(__name__)
        else:
            self.logging_service = None
            self.logger = logging.getLogger(__name__)
            # 确保日志器有处理器
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                handler.setFormatter(formatter)
                self.logger.addHandler(handler)
                self.logger.setLevel(logging.INFO)
        
        self.logger.info("文件服务初始化完成")
    
    def save_file(self, file_path, file_name, file_type="prd"):
        """
        保存文件
        
        Args:
            file_path: 文件路径
            file_name: 文件名
            file_type: 文件类型，默认为"prd"
            
        Returns:
            dict: 包含文件信息的字典
        """
        try:
            # 生成唯一文件ID
            file_id = str(uuid.uuid4())
            
            # 确保文件名安全
            safe_filename = secure_filename(file_name)
            if not safe_filename:
                safe_filename = f"{file_type}_{file_id}.md"
            
            # 创建目标路径
            target_path = os.path.join(self.upload_folder, safe_filename)
            
            # 保存文件
            with open(file_path, 'r', encoding='utf-8') as src_file, \
                 open(target_path, 'w', encoding='utf-8') as dst_file:
                content = src_file.read()
                dst_file.write(content)
            
            # 记录文件信息
            file_info = {
                "id": file_id,
                "name": safe_filename,
                "type": file_type,
                "path": target_path,
                "size": os.path.getsize(target_path),
                "created_at": datetime.now().isoformat()
            }
            
            if self.logging_service:
                self.logging_service.log_system_event("文件保存", f"文件已保存: {safe_filename}")
            else:
                self.logger.info(f"文件已保存: {safe_filename}")
            
            return file_info
            
        except Exception as e:
            if self.logging_service:
                self.logging_service.log_system_event("文件保存失败", f"保存文件失败: {str(e)}")
            else:
                self.logger.error(f"保存文件失败: {str(e)}")
            raise
    
    def get_file_info(self, file_id):
        """
        获取文件信息
        
        Args:
            file_id: 文件ID
            
        Returns:
            dict: 包含文件信息的字典，不存在则返回None
        """
        # 在上传目录中查找文件
        for filename in os.listdir(self.upload_folder):
            file_path = os.path.join(self.upload_folder, filename)
            if os.path.isfile(file_path):
                # 如果文件名包含ID或者是ID本身，则返回
                if file_id in filename or filename == file_id:
                    return {
                        "id": file_id,
                        "name": filename,
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "created_at": datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                    }
        
        # 如果在上传目录中没找到，检查输出目录
        for root, _, files in os.walk(self.outputs_folder):
            for filename in files:
                if file_id in filename:
                    file_path = os.path.join(root, filename)
                    return {
                        "id": file_id,
                        "name": filename,
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "created_at": datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                    }
        
        return None
    
    def get_task_result_file(self, task_id, file_type):
        """
        获取任务结果文件 - 增强错误处理和安全检查

        Args:
            task_id: 任务ID
            file_type: 文件类型 (excel, html, md, raw, json)

        Returns:
            dict: 包含文件信息的字典，不存在则返回None
        """
        from utils.security import is_valid_task_id, is_safe_path

        try:
            # 🔒 安全检查：验证 task_id 格式
            if not is_valid_task_id(task_id):
                self.logger.warning(f"无效的任务ID格式: {repr(task_id)}")
                return None

            # 根据文件类型确定目录
            folder_map = {
                'excel': self.excel_folder,
                'html': self.html_folder,
                'md': self.md_folder,
                'raw': self.raw_folder,
                'json': self.raw_folder  # JSON文件存储在raw目录
            }

            folder = folder_map.get(file_type)
            if not folder:
                self.logger.warning(f"不支持的文件类型: {file_type}")
                return None

            # 确保目录存在
            folder_abs = os.path.abspath(folder)
            if not os.path.exists(folder_abs):
                self.logger.warning(f"目录不存在: {folder_abs}")
                return None

            # 查找包含task_id的文件
            # 🔒 改进匹配逻辑：使用更严格的文件名匹配
            for filename in os.listdir(folder_abs):
                # 🔒 安全检查：验证文件名不包含危险字符
                if '..' in filename or '/' in filename or '\\' in filename:
                    continue

                # 🔒 更安全的匹配：task_id 必须被下划线、点或文件名边界包围
                # 防止通过部分匹配获取其他任务的文件
                # 支持的文件名格式：
                # - testcases_{prd_name}_{task_id}_{timestamp}.xlsx
                # - {task_id}_{filename}.md
                # - {prd_name}_{task_id}.json
                import re
                # 转义 task_id 中的特殊正则字符，然后构建匹配模式
                escaped_task_id = re.escape(task_id)
                # task_id 前后必须是下划线、点、或字符串边界
                pattern = rf'(^|[_.-]){escaped_task_id}([_.-]|$)'

                if re.search(pattern, filename):
                    file_path = os.path.join(folder_abs, filename)

                    # 🔒 验证最终路径在允许的目录内
                    if not is_safe_path(folder_abs, filename):
                        self.logger.warning(f"路径安全检查失败: {filename}")
                        continue

                    # 验证文件存在且可读
                    if os.path.exists(file_path) and os.access(file_path, os.R_OK):
                        file_info = {
                            'path': file_path,
                            'name': filename,
                            'size': os.path.getsize(file_path),
                            'type': file_type,
                            'created_at': datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                        }

                        self.logger.info(f"找到任务文件: {filename}, 大小: {file_info['size']} bytes")
                        return file_info
                    else:
                        self.logger.warning(f"文件存在但无法访问: {file_path}")

            self.logger.info(f"未找到任务文件: task_id={task_id}, file_type={file_type}")
            return None

        except Exception as e:
            self.logger.error(f"获取任务结果文件失败: {str(e)}")
            return None
    
    def save_test_cases_to_excel(self, test_cases, prd_name, task_id):
        """
        将测试用例保存为Excel文件
        
        Args:
            test_cases: 测试用例数据
            prd_name: PRD名称
            task_id: 任务ID
            
        Returns:
            Excel文件路径
        """
        # 创建时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 创建文件名，确保包含task_id以便后续查找
        file_name = f"testcases_{prd_name}_{task_id}_{timestamp}.xlsx"
        file_path = os.path.join(self.excel_folder, file_name)
        
        try:
            # 调试信息：打印测试用例数据
            self.logger.info(f"准备保存Excel文件: {file_name}")
            self.logger.info(f"测试用例数据类型: {type(test_cases)}, 内容: {str(test_cases)[:200]}...")
            
            # 将测试用例转换为DataFrame
            if isinstance(test_cases, list):
                if not test_cases:
                    # 如果列表为空，创建一个默认的DataFrame
                    df = pd.DataFrame([{"提示": "没有可用的测试用例数据"}])
                else:
                    # 处理<br>标签转换为Excel换行符
                    processed_test_cases = []
                    for case in test_cases:
                        processed_case = {}
                        for key, value in case.items():
                            if isinstance(value, str):
                                # 将<br>标签转换为Excel的换行符\n
                                processed_case[key] = value.replace('<br>', '\n').replace('<br/>', '\n').replace('<BR>', '\n').replace('<BR/>', '\n')
                            else:
                                processed_case[key] = value
                        processed_test_cases.append(processed_case)
                    df = pd.DataFrame(processed_test_cases)
            elif isinstance(test_cases, dict):
                # 处理单个测试用例字典
                processed_case = {}
                for key, value in test_cases.items():
                    if isinstance(value, str):
                        processed_case[key] = value.replace('<br>', '\n').replace('<br/>', '\n').replace('<BR>', '\n').replace('<BR/>', '\n')
                    else:
                        processed_case[key] = value
                df = pd.DataFrame([processed_case])
            else:
                # 如果是其他类型，尝试转换为字符串
                df = pd.DataFrame([{"原始数据": str(test_cases)}])
            
            # 辅助函数：转换 <br> 标签为换行符
            def convert_br_to_newline(value):
                if isinstance(value, str):
                    return value.replace('<br>', '\n').replace('<br/>', '\n').replace('<BR>', '\n').replace('<BR/>', '\n')
                elif isinstance(value, list) and value:
                    # 如果是列表，取第一个元素并转换
                    return convert_br_to_newline(value[0])
                return value if value else ''
            
            # 检测并修复旧格式数据（字段值错位问题）
            # 旧格式: id存功能模块, module存测试场景, scenario存用例编号
            if 'id' in df.columns and 'module' in df.columns and 'scenario' in df.columns:
                # 重新映射字段值（旧格式数据修复）
                df_fixed = pd.DataFrame()
                df_fixed['功能模块'] = df['id']  # id实际存的是功能模块
                df_fixed['测试场景分类'] = df['module']  # module实际存的是测试场景
                df_fixed['用例编号'] = df['scenario']  # scenario实际存的是用例编号
                df_fixed['用例名称'] = df['case_name'] if 'case_name' in df.columns else ''
                df_fixed['前置条件'] = df['precondition'].apply(convert_br_to_newline) if 'precondition' in df.columns else ''
                df_fixed['测试步骤'] = df['steps'].apply(convert_br_to_newline) if 'steps' in df.columns else ''
                df_fixed['预期结果'] = df['expected'].apply(convert_br_to_newline) if 'expected' in df.columns else ''
                df_fixed['优先级'] = df['priority'] if 'priority' in df.columns else 'P2'
                df_fixed['用例类型'] = df['test_type'] if 'test_type' in df.columns else '功能测试'
                df = df_fixed
            else:
                # 新格式数据，只需重命名列（如果有英文列名）
                column_mapping = {
                    'id': '用例编号',
                    'module': '功能模块',
                    'scenario': '测试场景分类',
                    'case_name': '用例名称',
                    'precondition': '前置条件',
                    'steps': '测试步骤',
                    'expected': '预期结果',
                    'priority': '优先级',
                    'test_type': '用例类型'
                }
                df.rename(columns=column_mapping, inplace=True)

            # 公开导出只保留测试人员需要使用的用例字段，防止内部追踪字段漏到 Excel。
            for hidden_column in HIDDEN_TEST_CASE_COLUMNS:
                if hidden_column in df.columns:
                    df.drop(columns=[hidden_column], inplace=True)
            public_columns = [column for column in PUBLIC_TEST_CASE_COLUMNS if column in df.columns]
            if public_columns:
                extra_columns = [
                    column for column in df.columns
                    if column not in public_columns and column not in HIDDEN_TEST_CASE_COLUMNS
                ]
                df = df[[*public_columns, *extra_columns]]
                
            # 保存到Excel，设置格式确保ID列保持文本格式
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='测试用例')
                
                # 获取工作表并设置格式
                workbook = writer.book
                worksheet = writer.sheets['测试用例']
                
                # 设置所有单元格的自动换行属性
                from openpyxl.styles import Alignment, NamedStyle
                
                # 创建换行样式
                wrap_alignment = Alignment(wrap_text=True, vertical='top')
                
                # 应用到所有数据单元格
                for row in range(1, len(df) + 2):  # 包括标题行
                    for col in range(1, len(df.columns) + 1):
                        cell = worksheet.cell(row=row, column=col)
                        cell.alignment = wrap_alignment
                        
                        # 如果是数据行且包含换行符，调整行高
                        if row > 1 and cell.value and isinstance(cell.value, str) and '\n' in cell.value:
                            # 根据换行符数量估算行高
                            line_count = cell.value.count('\n') + 1
                            worksheet.row_dimensions[row].height = max(20, line_count * 15)
                
                # 调整列宽以适应内容
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 5, 50)  # 限制最大宽度为50
                    worksheet.column_dimensions[column_letter].width = adjusted_width
                
                # 如果有id列，将其格式设置为文本
                if 'id' in df.columns or '用例编号' in df.columns:
                    id_col_name = 'id' if 'id' in df.columns else '用例编号'
                    id_col_index = df.columns.get_loc(id_col_name) + 1  # Excel列从1开始
                    id_col_letter = chr(ord('A') + id_col_index - 1)
                    
                    # 设置整列为文本格式
                    text_style = NamedStyle(name="text_style")
                    text_style.number_format = '@'  # 文本格式
                    text_style.alignment = wrap_alignment
                    
                    for row in range(2, len(df) + 2):  # 从第2行开始（跳过标题）
                        cell = worksheet[f'{id_col_letter}{row}']
                        cell.style = text_style
                        # 确保值是字符串
                        if cell.value is not None:
                            cell.value = str(cell.value)
            
            # 验证文件是否成功创建
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                if self.logging_service:
                    self.logging_service.log_system_event("Excel保存", f"测试用例已保存到Excel: {file_path}, 大小: {file_size} bytes")
                else:
                    self.logger.info(f"测试用例已保存到Excel: {file_path}, 大小: {file_size} bytes")
                
                return file_path
            else:
                raise Exception("文件创建失败")
                
        except Exception as e:
            if self.logging_service:
                self.logging_service.log_system_event("Excel保存失败", f"保存测试用例到Excel失败: {str(e)}")
            else:
                self.logger.error(f"保存测试用例到Excel失败: {str(e)}")
            return None
    
    def save_enhanced_prd(self, enhanced_prd, prd_name, task_id):
        """
        保存增强版PRD
        
        Args:
            enhanced_prd: 增强版PRD内容
            prd_name: PRD名称
            task_id: 任务ID
            
        Returns:
            PRD文件路径
        """
        # 创建时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 创建文件名
        file_name = f"{prd_name}_{timestamp}.md"
        file_path = os.path.join(self.md_folder, file_name)
        
        try:
            # 保存文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(enhanced_prd)
                
            if self.logging_service:
                self.logging_service.log_system_event("PRD保存", f"增强版PRD已保存: {file_path}")
            else:
                self.logger.info(f"增强版PRD已保存: {file_path}")
            return file_path
        except Exception as e:
            if self.logging_service:
                self.logging_service.log_system_event("PRD保存失败", f"保存增强版PRD失败: {str(e)}")
            else:
                self.logger.error(f"保存增强版PRD失败: {str(e)}")
            return None
    
    def save_raw_test_cases(self, test_cases, prd_name, task_id):
        """
        保存原始测试用例JSON
        
        Args:
            test_cases: 测试用例数据
            prd_name: PRD名称
            task_id: 任务ID
            
        Returns:
            JSON文件路径
        """
        # 创建时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 创建文件名
        file_name = f"testcases_{prd_name}_{timestamp}.json"
        file_path = os.path.join(self.raw_folder, file_name)
        
        try:
            # 保存文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(test_cases, f, ensure_ascii=False, indent=2)
                
            if self.logging_service:
                self.logging_service.log_system_event("JSON保存", f"原始测试用例已保存: {file_path}")
            else:
                self.logger.info(f"原始测试用例已保存: {file_path}")
            return file_path
        except Exception as e:
            if self.logging_service:
                self.logging_service.log_system_event("JSON保存失败", f"保存原始测试用例失败: {str(e)}")
            else:
                self.logger.error(f"保存原始测试用例失败: {str(e)}")
            return None
    
    def parse_test_cases_from_markdown(self, markdown_content):
        """
        从Markdown内容中解析测试用例表格
        
        Args:
            markdown_content: Markdown格式的内容
            
        Returns:
            pandas.DataFrame: 解析得到的测试用例数据框
        """
        try:
            import pandas as pd
            import io
            from io import StringIO
            
            # 调试信息
            self.logger.info(f"开始解析Markdown内容，长度: {len(markdown_content)}")
            
            # 查找所有Markdown表格
            import re
            
            # 使用更宽泛的表格匹配模式
            table_pattern = r'\|[^|]*\|[^|]*\|.*?\n(?:\|[^|]*\|[^|]*\|.*?\n)*'
            tables = re.findall(table_pattern, markdown_content, re.MULTILINE | re.DOTALL)
            
            if not tables:
                self.logger.warning("在Markdown内容中未找到表格")
                return None
                
            # 取最大的表格（通常是测试用例表格）
            largest_table = max(tables, key=len)
            self.logger.info(f"找到 {len(tables)} 个表格，选择最大的表格进行解析")
            
            # 将表格内容转换为DataFrame
            lines = largest_table.strip().split('\n')
            if len(lines) < 2:
                self.logger.warning("表格格式不正确，行数不足")
                return None
                
            # 解析表头
            header_line = lines[0]
            headers = [col.strip() for col in header_line.split('|') if col.strip()]
            
            # 跳过分隔符行，解析数据行
            data_rows = []
            for line in lines[2:]:  # 跳过表头和分隔符
                if line.strip() and '|' in line:
                    row_data = [col.strip() for col in line.split('|') if col.strip()]
                    if len(row_data) == len(headers):
                        data_rows.append(row_data)
            
            if not data_rows:
                self.logger.warning("表格中没有有效的数据行")
                return None
                
            # 创建DataFrame，保持原始数据不变（包括<br>标签）
            df = pd.DataFrame(data_rows, columns=headers)
            
            # 记录解析结果
            self.logger.info(f"成功解析测试用例表格: {len(df)} 行 x {len(df.columns)} 列")
            self.logger.info(f"表头: {list(df.columns)}")
            
            # 显示前几行数据用于调试（不显示<br>标签内容以避免日志混乱）
            if len(df) > 0:
                self.logger.info(f"示例数据（前3行）:")
                for i, row in df.head(3).iterrows():
                    # 为了日志可读性，将<br>标签简化显示
                    display_row = {}
                    for key, value in dict(row).items():
                        if isinstance(value, str) and '<br>' in value:
                            display_row[key] = value[:50] + '...[含<br>标签]' if len(value) > 50 else value + '[含<br>标签]'
                        else:
                            display_row[key] = value
                    self.logger.info(f"  行{i+1}: {display_row}")
            
            return df
            
        except Exception as e:
            self.logger.error(f"解析Markdown表格失败: {str(e)}")
            return None
