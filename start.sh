#!/bin/bash
# Spec2Case 启动脚本
# 设置必要的环境变量和启动应用
#
# 用法:
#   ./start.sh

export FLASK_ENV="${FLASK_ENV:-development}"
export SHOW_AI_COLLABORATION="${SHOW_AI_COLLABORATION:-True}"
echo "🔧 AI协作模块已启用"

# 设置 OpenMP 环境变量 (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    export LDFLAGS="-L/opt/homebrew/opt/libomp/lib"
    export CPPFLAGS="-I/opt/homebrew/opt/libomp/include"
    export DYLD_LIBRARY_PATH="/opt/homebrew/opt/libomp/lib:$DYLD_LIBRARY_PATH"
fi

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✅ 虚拟环境已激活"
else
    echo "⚠️  警告: 未找到虚拟环境 (.venv)"
fi

# 启动应用
echo "🚀 启动 Spec2Case..."
python app.py
