# RAG Framework

P3 已支持 CSV、结构化 Markdown、HTML 文件与 PDF 文本层导入。HTML 不执行脚本或抓取 URL。PDF 通过新增的 pypdf
依赖解析，不含 OCR；更新依赖并重启服务后可从 UI 选择 PDF。
格式、元数据与限制见 [数据源说明](docs/source-formats.md)。

P2 支持版本化 JSON Preset：通过 `RAG_SERVICE_PRESET` 加载；
`GET /v1/config/preset` 导出，`POST /v1/config/preset/validate` 校验，
`GET /v1/config/snapshot` 查看脱敏快照。评估报告保存配置快照与知识库 ID。
覆盖规则和密钥引用详见 [Preset 使用说明](docs/presets.md)。

P1 引入 `build_embedder()` / `build_vector_store()`。嵌入支持 `hash`、
`compatible`（OpenAI-compatible HTTP 协议，可连接 DashScope 兼容接口）与 `auto`。
远程模式需要独立配置 `RAG_EMBEDDING_MODEL/API_KEY/BASE_URL`，
及模型支持的 `RAG_EMBEDDING_DIMENSIONS`；不会自动复用聊天密钥。
默认仍为离线 Hash 384 维。详见 [索引安全与迁移](docs/index-safety.md)。

每个知识库的来源目录新增 `index-state.sqlite3`，保存模型/维度/分块/后端指纹与
可恢复 Document。旧索引无指纹，或配置不匹配时，查询与写入返回 409，须显式重建。
重建期间及失败后禁止使用半成品索引；原始数据和恢复日志保留。清空不删除恢复档案。
目前为单进程锁；部署时使用单个 worker。

P0-B：分块器使用 `RAG_CHUNKER_MODE=character`、
`RAG_CHUNK_SIZE=800`、`RAG_CHUNK_OVERLAP=120`。
融合使用 `RAG_FUSION_MODE=rrf`；可选的新键
`RAG_FUSION_RANK_CONSTANT` 优先于旧 `RAG_RRF_RANK_CONSTANT`，
冲突信息可在健康检查的 fusion 组件信息中查看。
修改分块参数仅影响后续写入；已有文档需显式重建才能重新分块。

`RAG_QUERY_PLANNER_MODE=disabled` 时使用
`RAG_DEFAULT_RETRIEVAL_STRATEGY=vector|keyword|hybrid` 固定策略，不调用分析模型、
不自动改写。重排由 `RAG_DEFAULT_RETRIEVAL_RERANK` 和重排 Provider 配置共同决定。

Python 扩展可继承 `contracts.providers.Chunker/Fusion` 并实现
`split/fuse`，可选覆盖 `parameters` 提供非敏感配置。
在构造服务前调用 `providers.algorithm_factory.chunkers.register(name, factory)`
或 `fusions.register(name, factory)`，工厂接收 Settings；重复名与未知模式会报错。
写入记录保留分块器类型和参数，Trace 保留融合实现及参数。

服务构造统一使用 `rag_framework.service.build_service(settings)`，返回
`ServiceRuntime`，支持通过 `knowledge_bases.runtime(id)` 获取指定库的管线，
使用结束后调用 `await service.close()`。`/health.components` 描述启动时的组件选择，
逐请求回退以 Trace 为准。原始来源和知识库目录分别通过
`RAG_SOURCE_DIRECTORY`（默认 `data/sources`）及
`RAG_KNOWLEDGE_BASE_DIRECTORY`（默认 `data/knowledge_bases`）配置。

## 数据源适配与文档目录

控制台「知识源」支持 TXT/Markdown（UTF-8）、平面 JSON 对象或对象数组、DOCX。
JSON 字段可使用标量或一维标量数组；对象、对象数组、嵌套数组暂不支持。
流程是上传原始文件、检查结构、选择 JSON 正文字段、预览 Document、确认入库。
未选 JSON 字段完整保存在 Document.metadata.raw_metadata；chunk 不复制该字典。
DOCX 按标准 Heading1–Heading9 样式划分章节，保留标题路径、章节和正文块位置，
表格按行及单元格分隔为文本。暂不支持 DOC、自定义标题样式映射、图片和 OCR。

`SourceAdapter.inspect` / `documents` 为统一扩展接口，通过 `AdapterRegistry.register`
注册新实现。适配器仅生成 Document，统一 IndexingPipeline 负责分块和索引。
默认知识库的原始文件和 SQLite 目录位于 `data/sources/`；其他知识库位于
`data/knowledge_bases/{id}/sources/`。目录保存每次上传的文件名、类型、大小、SHA-256、
结构检查结果，以及入库参数、时间、状态和新增/跳过数量。

新增接口：`POST /v1/sources?name=...&kind=text|json|docx`（原始文件请求体，10 MB 上限）、
`POST /v1/sources/{id}/preview`、`POST /v1/sources/{id}/ingest`（JSON body 含 content_fields）、
`GET /v1/sources`、`GET /v1/sources/documents`、`GET /v1/sources/runs`。

新流程按规范 Document 内容及业务元数据生成稳定 ID，成功写入的重复文档跳过；
失败后重试使用相同 chunk ID。上传历史保留独立记录，改名上传相同数据不会新增文档。
UI 直接文本入库也使用此流程。旧 `/v1/index/documents` 是低层接口，不执行目录去重；
已有旧索引不会自动迁移。当前写入采用单进程锁，记录列表尚未分页。

## 知识库管理

控制台可创建和切换知识库。默认库继续使用配置中的 Chroma collection 与
Elasticsearch index；新增库使用带知识库 ID 的独立 collection、index 和来源目录。
`Query.knowledge_base_id` 控制检索及回答所在的库，省略时使用 `default`。

- `GET /v1/knowledge-bases`：列出知识库及来源、Document、向量和关键词 chunk 计数。
- `POST /v1/knowledge-bases`：创建知识库，请求体为 `{"name":"产品文档"}`。
- `POST /v1/knowledge-bases/{id}/clear`：删除 Document 与检索索引，保留原始文件和历史。
- `POST /v1/knowledge-bases/{id}/rebuild`：按历史成功写入配置从原始文件重建。
- `/v1/knowledge-bases/{id}/sources...`：在指定知识库中上传、预览和写入来源。

清空属于派生数据重置，不删除来源文件；因此可审计且可恢复。服务仍是本机单进程版本，
暂未实现删除知识库、并发分布式锁和记录分页。

## 开发者控制台

运行 `python -m uvicorn rag_framework.api.main:app --host 127.0.0.1 --port 8000`，
浏览器访问 `http://127.0.0.1:8000/`。UI 静态资源随 Python 包提供，无需安装前端依赖。

控制台包含问答/仅检索、文档入库、Query 分析与阶段耗时、候选与重排排名、JSONL 测试集
导入导出、检索及端到端评估、历史报告详情。聊天目前使用完整响应接口；聊天记录仅保留在
当前页面内存中，刷新后清空。评估使用服务器当前配置，并显示真实失败或回退信息。
本版本面向本机开发，尚未提供身份认证，请将服务绑定到本机地址。

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

## 检索评估

`POST /v1/evaluations/retrieval` 使用标注了相关 chunk 的测试集运行当前真实检索链路，
并同时计算重排前 `candidates` 与重排后 `final_context` 的指标：Hit Rate、
Precision@K、Recall@K、MRR 和 NDCG@K。报告中的 `delta` 为重排后减去重排前，
因此负值表示该指标发生退化；报告总指标是所有成功样例的宏平均值。

```json
{
  "k": 5,
  "include_trace": false,
  "cases": [
    {
      "id": "tokyo-tower-height",
      "query": {"text": "东京塔有多高？"},
      "relevant_chunk_ids": ["tokyo-tower-001"],
      "metadata": {"dataset": "smoke-test"}
    }
  ]
}
```

批量评估会限制并发，单个检索失败不会中止整批任务。设置 `include_trace=true`
可在每个样例结果中保留完整 Trace；默认关闭以减小报告体积。报告以 JSON 文件持久化，
超过上限时自动移除最早的报告：

```env
RAG_EVALUATION_CONCURRENCY=4
RAG_EVALUATION_REPORT_LIMIT=100
RAG_EVALUATION_REPORT_DIRECTORY=data/evaluation/reports
```

- `GET /v1/evaluations`：按新到旧列出报告摘要。
- `GET /v1/evaluations/{report_id}`：读取包含逐样例结果的完整报告。

### JSONL 测试集

测试集采用一行一个 `EvaluationCase` 的 JSONL 格式。`query` 既可以是完整 Query 对象，
也可以直接使用字符串简写；导出时统一写成完整对象：

```jsonl
{"id":"case-1","query":"东京塔有多高？","relevant_chunk_ids":["tokyo-tower-001"]}
{"id":"case-2","query":{"text":"浅草寺在哪里？","filters":{"city":"东京"}},"relevant_chunk_ids":["sensoji-001"],"metadata":{"category":"location"}}
```

导入时使用 UTF-8 编码的 `application/x-ndjson` 请求体，`name` 和 `description`
作为查询参数传入。测试集和报告均默认保存在 `data/evaluation/`，该目录不会提交到 Git：

```env
RAG_EVALUATION_DATASET_DIRECTORY=data/evaluation/datasets
RAG_EVALUATION_DATASET_MAX_CASES=10000
RAG_EVALUATION_DATASET_MAX_BYTES=5000000
```

- `POST /v1/evaluation-datasets/import?name=Tokyo%20QA`：导入 JSONL 测试集。
- `GET /v1/evaluation-datasets`：列出测试集摘要。
- `GET /v1/evaluation-datasets/{dataset_id}`：读取完整测试集。
- `GET /v1/evaluation-datasets/{dataset_id}/export`：导出标准 JSONL。
- `POST /v1/evaluations/retrieval/datasets/{dataset_id}`：基于已保存测试集运行评估。

### 端到端 RAG 评估

`POST /v1/evaluations/rag` 会为每个样例执行一次完整的检索与回答生成，并在同一报告中返回
重排前后检索指标和以下回答质量指标：

- `groundedness`：回答词元被生成阶段实际上下文覆盖的比例。
- `answer_relevancy`：问题与回答词元集合的 F1 相似度。
- `citation_validity`：回答中指向有效上下文编号的引用比例。
- `citation_correctness`：引用内容是否真正支撑其对应回答陈述。
- `citation_precision`：被引用 chunk 中属于标注相关 chunk 的比例。
- `citation_recall`：标注相关 chunk 中被回答引用的比例。
- `reference_similarity`：存在 `reference_answer` 时，回答与参考答案的 F1 相似度。

```json
{
  "k": 5,
  "include_trace": false,
  "cases": [
    {
      "query": {"text": "东京塔有多高？"},
      "relevant_chunk_ids": ["tokyo-tower-001"],
      "reference_answer": "东京塔高333米。"
    }
  ]
}
```

回答评估支持 `heuristic`、`llm` 和 `auto` 三种裁判模式。`heuristic_v1` 完全在本地计算，
没有额外模型费用且结果可复现，适合持续集成和快速回归。`llm_judge_v1` 使用结构化
LLM 输出评估 groundedness、answer relevancy、citation correctness 和参考答案语义一致性；
引用编号有效性、标注 chunk 命中率等可精确计算的指标仍由本地计算。

```env
RAG_EVALUATION_JUDGE_MODE=auto
# 未设置时依次复用回答生成和 Planner 的模型、密钥与 Base URL。
# RAG_EVALUATION_JUDGE_MODEL=qwen-plus
# RAG_EVALUATION_JUDGE_API_KEY=your-api-key
# RAG_EVALUATION_JUDGE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RAG_EVALUATION_JUDGE_TEMPERATURE=0
RAG_EVALUATION_JUDGE_REQUEST_TIMEOUT=60
RAG_EVALUATION_JUDGE_MAX_RETRIES=2
RAG_EVALUATION_JUDGE_MAX_TOKENS=1024
RAG_EVALUATION_JUDGE_MAX_CONTEXT_CHARACTERS=12000
```

`llm` 是严格模式，凭据缺失会阻止启动，调用或结构化输出失败会将对应样例标记为失败。
`auto` 优先使用 LLM，初始化失败时切换成本地裁判；运行时失败则逐样例回退，并通过
`fallback_used` 和 `fallback_reason` 记录回退。`heuristic` 始终使用本地指标，也是默认模式，
避免评估任务在未明确配置时产生额外模型费用。报告中的 `judge_rationale` 只保存简短结论，
不要求也不保存模型的思维链。

真实 Provider 烟雾测试默认跳过，显式设置 `RAG_RUN_LIVE_JUDGE=1` 后执行测试即可验证
当前 `.env` 中配置的模型是否支持结构化裁判输出。

- `POST /v1/evaluations/rag`：直接提交样例并运行端到端评估。
- `POST /v1/evaluations/rag/datasets/{dataset_id}`：使用持久化测试集运行端到端评估。
- `GET /v1/evaluations`：统一列出 `retrieval` 与 `rag` 两类实验报告。
