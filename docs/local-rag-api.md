# 本地统一非流式 RAG API（2026-10-08）

## 手动测试脚本

在项目根目录运行（仅使用 Python 标准库）：

```powershell
.venv\Scripts\python.exe scripts\test_local_rag.py --query "东京有哪些赏樱景点？" --knowledge-base-id default
.venv\Scripts\python.exe scripts\test_local_rag.py --query "你的问题" --knowledge-base-id "实际知识库ID" --include-trace --json
```

通过 --url 修改完整端点，--timeout 调整客户端超时，--conversation-id 标记 Trace 归组，--history 可重复传历史文本。实际运行会使用当前生效模型配置，可能产生云端调用费用。脚本不会导入/删除数据或更改配置。退出码 0 为接口正常响应（可能无证据或降级），1 为连接/HTTP/响应格式错误，2 为空回答。

端点 POST /v1/rag，复用现有流水线与已应用配置，不读取工作台草稿，不允许请求覆盖模型、密钥和检索参数。此阶段无认证及多用户隔离，仅供本地可信应用使用；服务应绑定 127.0.0.1，不向公网直接暴露。

请求示例：

```json
{"query":"东京有哪些赏樱景点？","knowledge_base_id":"default","conversation_id":"local-session-1","history":[],"include_trace":false}
```

history 由调用方提供；conversation_id 仅用于 Trace 归组，不会自动加载历史或自动创建会话。嵌入配置取目标知识库绑定，其他参数取工作台已生效共享配置；请求门禁阻止过程中热配置替换。

响应包含 answer、generation（model/fallback_used/status）、实际回答 citations、最终参与生成的 contexts、trace_id、request_id（同 trace_id）、config_version、全局 config_hash 与 duration_ms。include_trace=true 时增加完整 trace；默认不返回该字段。contexts 使用现有 RetrievedChunk 结构：chunk、score、source、rank 等。

generation.status：completed 正常生成、fallback 已降级、no_context 无证据、empty_answer 空回复；fallback_used 独立表明是否降级。未将空回复伪装成正常完成。失败使用 HTTP 错误并返回安全原因和可用 trace_id，不回显供应商响应。未知知识库 404、参数非法 422、索引不兼容 409、执行错误 500。

完整记录可通过 GET /v1/traces/{trace_id} 追溯，保留受现有 Trace 容量限制。config_hash 是全局非敏感配置摘要，不等同目标库嵌入身份；库索引身份可在 Trace/管理接口查看。引用只包含回答实际标记的来源，不自动将所有上下文视作引用。

原有 /v1/chat 与流式接口保持兼容。未修改真实知识库及工作台生效配置。

Python 本地调用示例（标准库，无额外依赖）：

```python
import json
from urllib.request import Request, urlopen

payload = {"query": "东京有哪些赏樱景点？", "knowledge_base_id": "default"}
request = Request("http://127.0.0.1:8011/v1/rag",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}, method="POST")
with urlopen(request, timeout=120) as response:
    result = json.load(response)
print(result["answer"])
print(result["trace_id"])
```

验证：新增 7 项端点测试通过，完整回归 259 项通过、4 项跳过，未调用真实云端模型。
