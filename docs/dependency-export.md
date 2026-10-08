# 固定版本依赖导出（2026-10-08）

根目录 requirements.txt 为当前项目 .venv 的 pip freeze 快照，包含直接与间接依赖、已安装可选后端和测试工具。移除了项目自身 editable Git 安装记录，避免下载旧提交或要求 SSH 权限；pywin32 标记为仅 Windows 安装。

```powershell
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
```

这是当前环境快照，不是跨平台锁文件，其他 Python 版本/平台仍可能受到 wheel 可用性限制。pyproject.toml 仍是项目声明依赖来源。未安装的可选本地 sentence-transformers 模型依赖不在本快照中，需要时单独安装对应 extra。不包含 .env 或 API Key。
