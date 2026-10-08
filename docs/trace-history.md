# 对话 Trace 追溯

一个 conversation_id 对应一次对话，每次 Query 产生独立 trace.id，每个阶段拥有独立 step.id。
前端每次请求创建折叠卡片；最新请求展开，旧记录折叠，聊天消息提供定位按钮。
Trace ID 可复制或输入查找；阶段链接格式为 #trace=<id>&step=<id>。

API：
- GET /v1/traces?conversation_id=<id>&limit=100（最大 500）
- GET /v1/traces/<trace_id>
- GET /v1/traces/<trace_id>/steps/<step_id>

返回记录包含 trace 及可选 answer。记录保留实际候选/上下文的正文、元数据与分数快照；
知识库更新不改变旧快照。生成提示词哈希、配置身份沿用已有阶段详情。
接口覆盖 /v1/retrieve、/v1/chat、/v1/chat/stream，评估执行暂不单独归档至此存储。
流式接口新增首个 trace 事件返回 trace_id；错误事件也带 trace_id。
失败保存已完成阶段和错误类型，不返回供应商异常中的敏感文本。

SQLite 位于 source_directory 的父目录下 traces/traces.sqlite3（默认 data/traces），
当前最多保留最近 1000 次请求。超过数量自动移除最早记录。Git 忽略默认存储目录。
每次请求开始写入 running 记录，结束或异常保存 completed/failed；
服务硬退出时可能留下 running 记录，前端恢复时显示执行未完成。
此阶段不实时写入每一个阶段，也不支持自动续跑中断请求。

当前对话 ID 在浏览器 localStorage 保存，刷新恢复最多最近 500 条 Trace 与回答。
新对话或切换知识库生成新 conversation_id，旧记录仍可通过 Trace ID 查找。
点击历史 Trace 不会把旧查询注入当前聊天上下文。
Trace 查询接口沿用当前本地开发服务的访问边界；部署共享环境需补鉴权与隔离。
