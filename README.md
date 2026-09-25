# RAG Framework

## 重排

支持 `disabled`、`cross_encoder`、`cloud` 和 `auto`。`cloud` 使用云端服务且失败时报错；
`auto` 在云端 URL 和密钥齐全时优先使用云端，否则使用本地 CrossEncoder，运行失败时恢复原始召回顺序并记录异常类型。

DashScope `gte-rerank-v2` 使用 `dashscope` 协议及 SDK 默认端点：

```env
RAG_RERANKER_MODE=cloud
RAG_RERANKER_CLOUD_PROTOCOL=dashscope
RAG_RERANKER_CLOUD_MODEL=gte-rerank-v2
RAG_RERANKER_CLOUD_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
RAG_RERANKER_CLOUD_API_KEY=your-dashscope-api-key
```

使用结果位于响应顶层 `results` 的兼容接口时，将协议改为 `compatible`。
请求始终要求云端返回全部候选；返回索引缺失、重复、越界或分数非法时视为失败。

本地 CrossEncoder 需安装可选依赖 `pip install -e ".[rerank]"`，并配置
`RAG_RERANKER_MODEL=本地模型路径`。默认模型名称仅用于英文入门测试；
中文场景请配置适合中文的 CrossEncoder。
默认模型名称仅用于英文入门测试；中文场景请配置适合中文的 CrossEncoder。

模型按首次请求懒加载，默认 `RAG_RERANKER_LOCAL_FILES_ONLY=true`，
不会自动下载权重。需要下载时可显式设置为 false。
`RAG_RERANKER_DEVICE` 控制 CPU/GPU，`RAG_RERANKER_BATCH_SIZE` 控制推理批次。
健康接口中的 lazy 表示已配置，不代表权重已经成功加载。

`RAG_RERANKER_CANDIDATE_K=32` 控制重排候选池；最终返回数量仍由
Planner 的 top_k 控制。Trace 保留原始 candidates 和 rerank_comparison，
后者包含每个候选的原排名、新排名、召回分数与重排分数，以及失败回退原因。
不同分数体系不可直接比较数值；排名对比也不等同于检索质量评估。

真实模型集成测试通过 `RAG_TEST_RERANK_MODEL` 指向缓存模型或本地路径启用；
未设置时跳过，不下载权重。普通测试使用模拟预测器验证排序与回退。

面向开发者的可观测 RAG 框架。第一版提供 Chroma 默认实现、可插拔提供方契约、自适应检索路由和完整检索追踪。

## 设计目标

- 数据源、嵌入模型、向量数据库、重排模型与 LLM 解耦。
- 对每次检索记录路由、改写、候选、重排、上下文与耗时。
- 用统一的实验配置支撑检索策略与 RAG 评估对比。

## 当前阶段

后端最小闭环：文档入库、Chroma 向量检索、结构化 Query Planner 与检索 Trace API。默认提供低延迟规则规划器；任意支持结构化 JSON 输出的 LLM 均可通过 `LLMQueryPlanner` 接入，并在错误时回退到规则规划器。

## 自适应 Query Planner

规划结果分为两部分：

- `QueryAnalysis`：查询类型、规范化 Query、关键词、过滤条件、是否改写、改写列表、理由和置信度。
- `RetrievalDecision`：选择 `vector`、`keyword` 或 `hybrid`，以及 `top_k`、是否重排、理由和置信度。

当前规则规划器识别精确标识符、事实查询、语义问题、过滤查询、比较、多跳问题和对话追问。LLM 规划器会约束结构化输出、清理重复改写，并始终保留原始 Query；低置信度或歧义结果自动切换到 hybrid，模型调用或格式校验失败则回退到规则规划器。

检索 Trace 将规划过程拆分为 `analyze_query`、`rewrite_query`（需要时）和 `select_retrieval_strategy`，并记录规划器类型、回退原因、最终生效的 Query 列表和完整决策。旧版 `QueryRouter`、`HeuristicQueryRouter` 与 `LLMQueryRouter` 名称仍作为兼容别名保留。

安装并启用 OpenAI-compatible LLM Planner：

```powershell
python -m pip install -e ".[dev,llm]"
Copy-Item .env.example .env
```

```env
RAG_QUERY_PLANNER_MODE=auto
RAG_PLANNER_MODEL=gpt-4o-mini
RAG_PLANNER_API_KEY=your-api-key
# 使用其他 OpenAI-compatible 服务时设置：
# RAG_PLANNER_BASE_URL=https://your-provider.example/v1
```

`heuristic` 始终使用规则规划器；`llm` 要求有效的 API Key 并在初始化失败时阻止启动；`auto` 在配置了 API Key 时启用 LLM，否则安全切换到规则规划器。`/health` 会返回配置模式、实际运行模式、Provider 和启动回退原因。`POST /v1/query/plan` 可单独查看分析、改写和策略选择，不会执行向量或关键词检索。

## 回答生成与引用

Generation Pipeline 在检索完成后将最终上下文编号，要求模型只依据上下文回答，并使用 `[1]` 格式添加行内引用。返回结果会将引用编号解析为 `chunk_id`、`document_id`、来源地址和内容预览；生成模型、上下文数量、引用数量、输出长度与耗时会写入同一个 Trace。

- `POST /v1/chat`：返回完整回答、结构化引用和检索/生成 Trace。
- `POST /v1/chat/stream`：通过 SSE 依次返回 `retrieval`、`token` 和 `complete` 事件；失败时返回终止 `error` 事件。

生成模型默认复用 Planner 的模型、API Key 与 Base URL，也可独立覆盖：

```env
RAG_ANSWER_GENERATOR_MODE=auto
# RAG_GENERATION_MODEL=qwen3.7-plus
# RAG_GENERATION_API_KEY=your-generation-key
# RAG_GENERATION_BASE_URL=https://your-provider.example/v1
RAG_GENERATION_REQUEST_TIMEOUT=60
RAG_GENERATION_MAX_TOKENS=1024
RAG_GENERATION_MAX_CONTEXT_CHUNKS=8
```

`extractive` 模式不调用 LLM，只返回带引用的检索证据；`llm` 模式要求可用凭据；`auto` 优先使用 LLM，在未配置凭据或 Provider 初始化失败时使用 extractive 安全回退。

当前支持的检索执行策略：

- `vector`：Chroma 向量召回。
- `keyword`：支持英文词项及中日韩字符/二元组的 BM25 召回。
- `hybrid`：并行执行向量与 BM25 召回，通过 RRF 融合排名。

每个检索结果都会保留向量、关键词和 RRF 分数，`RetrievalTrace` 同时记录路由、召回、融合、回退与重排步骤。默认 BM25 索引位于进程内；后续知识库版本模块将负责持久化和启动恢复。

## Elasticsearch BM25

Elasticsearch 是可选的生产关键词检索后端。向量检索仍使用 Chroma，RRF 仍由应用层执行，因此两类存储可以独立替换，Trace 也能保留两路原始候选。

```powershell
python -m pip install -e ".[dev,elasticsearch]"
Copy-Item .env.example .env
```

在 `.env` 中设置：

```env
RAG_KEYWORD_BACKEND=elasticsearch
RAG_ELASTICSEARCH_URL=http://localhost:9200
RAG_ELASTICSEARCH_INDEX=rag_chunks
```

Elasticsearch 写入使用异步 Bulk 和 `refresh=wait_for`。每次入库同时维护内存 BM25 镜像；连接或查询失败时自动降级到内存索引，并在 Retrieval Trace 中将来源标记为 `keyword:memory:fallback`。

混合检索参数可通过环境变量调整：

```env
RAG_HYBRID_CANDIDATE_MULTIPLIER=2
RAG_RRF_RANK_CONSTANT=60
```
