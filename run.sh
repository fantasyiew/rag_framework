#!/usr/bin/env bash
# ============================================================
#  RAG Framework 启动脚本 (Git Bash / WSL)
#  激活 .venv 虚拟环境并运行 app (uvicorn, http://127.0.0.1:8000)
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

# 检查虚拟环境是否存在
if [[ ! -x ".venv/Scripts/python.exe" && ! -x ".venv/bin/python" ]]; then
    echo "[ERROR] 未找到虚拟环境 .venv 下的 python 解释器"
    echo "        请先运行: python -m venv .venv && .venv/Scripts/pip install -e '.[dev]'"
    exit 1
fi

# 激活虚拟环境 (兼容 Windows 的 Scripts/ 与 Linux 的 bin/)
if [[ -f ".venv/Scripts/activate" ]]; then
    source ".venv/Scripts/activate"
else
    source ".venv/bin/activate"
fi

# 运行应用
python main.py
