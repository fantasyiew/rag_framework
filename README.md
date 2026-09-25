# RAG Framework

面向开发者的可观测 RAG 框架。第一版提供 Chroma 默认实现、可插拔提供方契约、自适应检索路由和完整检索追踪。

## 设计目标

- 数据源、嵌入模型、向量数据库、重排模型与 LLM 解耦。
- 对每次检索记录路由、改写、候选、重排、上下文与耗时。
- 用统一的实验配置支撑检索策略与 RAG 评估对比。

## 当前阶段

后端最小闭环：文档入库、Chroma 向量检索、受约束的查询路由与检索 Trace API。默认提供规则路由；任意支持结构化 JSON 输出的 LLM 均可通过 `LLMQueryRouter` 接入，并在错误时回退到规则路由。

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
