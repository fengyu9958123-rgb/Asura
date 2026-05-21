#!/usr/bin/env python3
"""
数据清除脚本
用于清除autogen-web-api项目中的所有历史数据、日志和临时文件
"""

import os
import shutil
import sqlite3
from pathlib import Path

def clear_database():
    """清除数据库中的所有数据"""
    print("🗄️ 清除数据库数据...")
    
    db_path = "data/autogen.db"
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 获取所有表名
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            # 清空所有表
            for table in tables:
                table_name = table[0]
                if table_name != 'sqlite_sequence':  # 跳过系统表
                    cursor.execute(f"DELETE FROM {table_name};")
                    print(f"  ✅ 清空表: {table_name}")
            
            # 重置自增ID（如果表存在）
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence';")
            if cursor.fetchone():
                cursor.execute("DELETE FROM sqlite_sequence;")
                print(f"  ✅ 重置自增ID序列")
            
            conn.commit()
            conn.close()
            print("  ✅ 数据库清除完成")
        except Exception as e:
            print(f"  ❌ 数据库清除失败: {e}")
    else:
        print("  ℹ️ 数据库文件不存在")

def clear_directory(dir_path, description):
    """清除指定目录中的所有文件"""
    print(f"📁 清除{description}...")
    
    if os.path.exists(dir_path):
        try:
            # 遍历目录中的所有文件和子目录
            for item in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item)
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    print(f"  ✅ 删除文件: {item}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    print(f"  ✅ 删除目录: {item}")
            print(f"  ✅ {description}清除完成")
        except Exception as e:
            print(f"  ❌ {description}清除失败: {e}")
    else:
        print(f"  ℹ️ {description}目录不存在")

def clear_files_in_directory(dir_path, description):
    """清除目录中的文件但保留目录结构"""
    print(f"📄 清除{description}...")
    
    if os.path.exists(dir_path):
        try:
            for root, dirs, files in os.walk(dir_path):
                for file in files:
                    if not file.startswith('.'):  # 保留隐藏文件
                        file_path = os.path.join(root, file)
                        os.remove(file_path)
                        rel_path = os.path.relpath(file_path, dir_path)
                        print(f"  ✅ 删除文件: {rel_path}")
            print(f"  ✅ {description}清除完成")
        except Exception as e:
            print(f"  ❌ {description}清除失败: {e}")
    else:
        print(f"  ℹ️ {description}目录不存在")

def clear_log_files():
    """清除根目录下的日志文件"""
    print("📝 清除根目录日志文件...")
    
    log_files = [
        "app.log",
        "app_log.txt", 
        "nohup.out"
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
                print(f"  ✅ 删除日志文件: {log_file}")
            except Exception as e:
                print(f"  ❌ 删除日志文件失败 {log_file}: {e}")
        else:
            print(f"  ℹ️ 日志文件不存在: {log_file}")

def clear_backup_files():
    """清除数据库备份文件"""
    print("💾 清除数据库备份文件...")
    
    data_dir = "data"
    if os.path.exists(data_dir):
        for file in os.listdir(data_dir):
            if file.startswith("autogen.db.backup_"):
                backup_path = os.path.join(data_dir, file)
                try:
                    os.remove(backup_path)
                    print(f"  ✅ 删除备份文件: {file}")
                except Exception as e:
                    print(f"  ❌ 删除备份文件失败 {file}: {e}")

def main():
    """主函数"""
    print("🚀 开始清除autogen-web-api历史数据...")
    print("=" * 50)
    
    # 1. 清除数据库数据
    clear_database()
    
    # 2. 清除日志目录
    clear_directory("logs", "日志目录")
    
    # 3. 清除上传文件
    clear_files_in_directory("uploads", "上传文件")
    
    # 4. 清除输出文件
    clear_files_in_directory("outputs", "输出文件")
    clear_files_in_directory("test_outputs", "测试输出文件")
    
    # 5. 清除临时数据
    clear_files_in_directory("data/tasks", "任务数据")
    clear_files_in_directory("data/data", "临时数据")
    
    # 6. 清除根目录日志文件
    clear_log_files()
    
    # 7. 清除数据库备份文件
    clear_backup_files()
    
    print("=" * 50)
    print("🎉 数据清除完成！")
    print("\n📋 已清除的内容:")
    print("  • 数据库中的所有任务和记录")
    print("  • 所有日志文件和API会话记录")
    print("  • 上传的PRD文件")
    print("  • 生成的测试用例文件(Excel/JSON/MD)")
    print("  • 临时数据和缓存文件")
    print("  • 数据库备份文件")
    print("\n✅ 系统已重置为初始状态，可以进行新的测试")

if __name__ == "__main__":
    # 确保在项目根目录运行
    if not os.path.exists("app.py"):
        print("❌ 请在项目根目录运行此脚本")
        exit(1)
    
    main()