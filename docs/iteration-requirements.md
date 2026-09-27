# RAG Framework 迭代需求说明书

> 主题：组件可插拔化与配置驱动改造
> 版本：v0.2.1（评审修订稿）
> 日期：2026-09-27
> 状态：已评审，待实施
> 关联代码基线：`src/rag_framework/`（contracts / providers / pipeline / sources / evaluation / config）

---

## 1. 目标与范围

### 1.1 总目标

将框架从「单一默认实现 + 部分硬编码」演进为**高度可定制、配置驱动、组件可插拔**的 RAG 框架：

1. 所有算法类组件提供**抽象接口（契约）**，用户可自定义实现并注册扩展；
2. 所有默认算法提供**参数配置**（如分块 `chunk_size`、`overlap`）；
3. 组件选择与参数统一由**配置**驱动，运行时可观测「配置值 vs 实际生效值」；
4. 用户在实验/评估达到预期后，可基于**统一上层对话接口**获得定制化的 RAG 服务。

### 1.2 设计原则

- **面向契约（Contract-first）**：Pipeline 只依赖 `contracts/providers.py` 中的抽象类型，不依赖具体实现。
- **工厂 + 注册表（Factory + Registry）**：实现类通过工厂按配置构建；用户自定义实现通过注册表接入，不改核心代码。
- **渐进降级（Fail-safe）**：组件缺失/初始化失败时，采用明确的回退策略（类似现有 `auto` 模式），不静默破坏检索。
- **持久化兼容优先**：涉及索引语义的核心组件不得跨模型静默降级；配置变化必须校验索引指纹并显式重建。
- **可观测（Observable）**：Trace 与 `/health` 记录每个组件的实际实现、参数、耗时与回退原因。
- **向后兼容**：已有配置键、API 路由、Trace 结构不破坏。
- **密钥隔离**：Preset、Trace、评估报告和健康检查只保存脱敏配置，禁止持久化 API Key。

### 1.3 术语

| 术语 | 含义 |
|---|---|
| 契约 / Port | `contracts/providers.py` 中定义的抽象基类（ABC） |
| 工厂 | `build_xxx(settings)` 之类的配置驱动构造器 |
| 注册表 | 用户/插件注册自定义实现的容器（如 `AdapterRegistry`） |
| 配置驱动 | 通过 `.env` / `Settings` 决定组件选择与参数 |
| 预设（Preset） | 一组经过验证的完整配置快照，用于复现与导出服务 |

---

## 2. 现状基线（改造前）

| 组件 | 契约 | 工厂 | 配置项 | 现状 |
|---|---|---|---|---|
| 数据源解析 | ✅ `SourceAdapter` | ✅ `AdapterRegistry` | 部分（`kind` 分发） | 已支持扩展，内置 text/json/docx |
| 嵌入模型 | ✅ `Embedder` | ❌ | ❌（仅 `embedding_dimensions`） | 硬编码 `HashEmbedder` |
| 分块算法 | ❌ 无 `Chunker` 契约 | ❌ | ❌ | 硬编码 `CharacterChunker`（800/120 写死） |
| 向量数据库 | ✅ `VectorStore` | ❌ | ❌ | 硬编码 `ChromaVectorStore` |
| QueryPlanner | ✅ `QueryPlanner` | ✅ | ✅ `RAG_QUERY_PLANNER_MODE` | 支持 heuristic/llm/auto |
| Reranker | ✅ `Reranker` | ✅ | ✅ `RAG_RERANKER_MODE` | 支持 disabled/cross_encoder/cloud/auto |
| 融合算法 | ❌ 无 `Fusion` 契约 | ❌ | ❌（`rrf_rank_constant` 而已） | 硬编码 RRF |
| KeywordStore | ✅ `KeywordStore` | ✅ | ✅ `RAG_KEYWORD_BACKEND` | 支持 memory/elasticsearch |
| 评估算法 | 部分（`AnswerJudge`） | 部分 | 部分 | 检索指标/裁判已有，指标不可自定义 |
| 服务构造 | ❌ | ❌ | 部分 | API 模块存在全局构造，知识库运行时有重复装配逻辑 |
| 知识库管理 | 部分 | ✅ `KnowledgeBaseManager` | 部分 | 已支持创建、切换、清空、重建和索引隔离；尚无组件指纹清单 |

---

## 3. 数据接入层

### 3.1 数据源解析与统一结构化

**目标**：不同格式数据源统一解析为 `Document`，支持用户注册自定义解析算法。

**现状**：已有 `SourceAdapter` 契约（`inspect` / `documents`）与 `AdapterRegistry`，内置 PlainText/Json/Docx。

**需求点**：

- [ ] **D1-1** 扩展内置适配器：新增 PDF、CSV、Markdown（结构化标题）、网页（HTML）等常见格式。
- [ ] **D1-2** `AdapterOptions` 参数化：支持每格式的解析参数（分隔符、编码、是否 OCR 等）。请求参数负责单次写入选择，`RAG_SOURCE_*` 只提供默认值，不覆盖已记录的写入配置。
- [ ] **D1-3** 注册机制配置化：支持通过配置/入口脚本声明额外 adapter，无需修改核心代码。
- [ ] **D1-4** 解析结果统一为 `Document` 模型，元数据字段（`source_type`、`record_index`、`heading_path` 等）规范化。

**验收标准**：

1. 新增一种格式 = 新增一个 `SourceAdapter` 子类并注册，核心代码零改动。
2. 所有 adapter 输出结构一致的 `Document` 列表。
3. 解析失败抛出可读的 `ValueError`，且不影响其他来源。

### 3.2 嵌入模型（Embedding Model）

**目标**：嵌入模型成为可配置、可替换的组件。

**现状**：硬编码 `HashEmbedder`（哈希假嵌入），仅有 `embedding_dimensions`（默认 384）。

**需求点**：

- [ ] **D2-1** 新增工厂 `build_embedder(settings) -> Embedder`。
- [ ] **D2-2** 新增配置项 `RAG_EMBEDDING_MODE`，取值建议：`hash`（默认）/ `openai` / `local`（sentence-transformers）/ `dashscope`。
- [ ] **D2-3** 嵌入模型参数配置：`RAG_EMBEDDING_MODEL`、`RAG_EMBEDDING_API_KEY`、`RAG_EMBEDDING_BASE_URL`、`RAG_EMBEDDING_DIMENSIONS`、`RAG_EMBEDDING_BATCH_SIZE`。
- [ ] **D2-4** 索引兼容校验：知识库首次写入时保存 Embedding 指纹（provider、model、dimensions、可用时记录版本）；后续启动、写入和查询均校验指纹。维度不同或模型身份不一致时给出明确错误并要求重建。
- [ ] **D2-5** `auto` 仅用于空知识库启动时选择实现。已有索引的知识库必须使用其指纹对应的 Embedder；远程服务不可用时应 fail-closed，不得自动回退 `hash` 并混用向量空间。`/health` 暴露选择结果或阻塞原因。

**验收标准**：

1. 切换嵌入模型仅改配置，不改 pipeline 代码。
2. 模型身份或维度不一致时给出明确报错，而非静默写坏数据。
3. `/health` 返回 `configured` vs `active` 嵌入模式及回退原因。
4. 修改 Embedding 配置后，只有显式重建才能更新知识库索引指纹。

### 3.3 分块算法（Chunker）

**目标**：分块算法抽象化，默认分块器参数可配置。

**现状**：`CharacterChunker` 为具体类、无契约、`chunk_size=800`/`overlap=120` 写死，`IndexingPipeline` 直接依赖具体类型。

**需求点**：

- [ ] **D3-1** 在 `contracts/providers.py` 新增 `Chunker(ABC)`：`split(document) -> list[Chunk]`。
- [ ] **D3-2** `CharacterChunker` 继承 `Chunker`，`IndexingPipeline` 依赖 `Chunker` 而非具体类。
- [ ] **D3-3** 分块参数配置化：`RAG_CHUNK_SIZE`、`RAG_CHUNK_OVERLAP`（默认沿用 800/120）。
- [ ] **D3-4**（可选）支持多种分块策略：`RAG_CHUNKER_MODE`（`character` 默认 / `sentence` / `semantic` / `heading`），配套工厂 `build_chunker(settings)`。

**验收标准**：

1. 分块参数通过配置调整，无需改代码。
2. 自定义分块器实现 `Chunker` 契约即可替换。
3. 写入运行记录和知识库索引清单记录分块器类型与参数；检索 Trace 不重复记录未参与检索执行的分块步骤。

### 3.4 向量数据库（含检索）

**目标**：向量库可配置、可替换，检索行为与具体库解耦。

**现状**：硬编码 `ChromaVectorStore`，仅 `chroma_directory` / `chroma_collection` 两个 Chroma 专属配置。

**需求点**：

- [ ] **D4-1** 新增工厂 `build_vector_store(settings) -> VectorStore`。
- [ ] **D4-2** 新增配置项 `RAG_VECTOR_BACKEND`（`chroma` 默认；预留 `pgvector` / `qdrant` / `milvus`）。
- [ ] **D4-3** 向量库连接参数配置化（路径、集合名、连接串、是否重建索引等），与具体后端对应。
- [ ] **D4-4** `VectorStore` 保持最小检索契约（`upsert` / `search`）；另定义管理与生命周期能力契约，如 `IndexAdmin(count/clear)`、`HealthCheck`、`AsyncClosable`。Pipeline 只依赖最小契约，知识库管理层依赖显式能力契约。
- [ ] **D4-5** 数据迁移/重建工具：切换后端后可将既有 `Document` 重建索引。

**验收标准**：

1. 切换向量库仅改配置，检索 pipeline 代码零改动。
2. `top_k` / `filters` 行为在各后端语义一致。
3. 所有可用于知识库管理的后端明确实现统计、清空、健康检查和关闭能力，不使用隐式 `getattr` 探测。

---

## 4. 检索层

### 4.1 QueryPlanner（可选禁用）

**目标**：规划器可禁用；禁用时用户可指定单一检索算法。

**现状**：`RAG_QUERY_PLANNER_MODE` 仅 `heuristic | llm | auto`。

**需求点**：

- [ ] **R1-1** 扩展 `RAG_QUERY_PLANNER_MODE`，新增 `disabled`。
- [ ] **R1-2** 新增配置项 `RAG_DEFAULT_RETRIEVAL_STRATEGY`（`vector | keyword | hybrid`），在禁用规划时生效。
- [ ] **R1-3** 禁用模式下构造一个「直通规划器」（返回固定 `RetrievalPlan`，`planner="disabled"`），Trace 记录 `planner=disabled` 与跳过规划的原因。
- [ ] **R1-4** `disabled` 模式下不执行自动 Query Rewrite，但重排仍可独立配置。若后续需要无 Planner 改写，单独引入 `QueryRewriter` 契约。

**验收标准**：

1. 设置 `RAG_QUERY_PLANNER_MODE=disabled` 后，检索直接使用指定单一策略。
2. Trace 明确标注未经过查询分析/策略选择。

### 4.2 Rerank 配置

**目标**：重排能力保持可配置，补充常用参数与 provider。

**现状**：已支持 `disabled | cross_encoder | cloud | auto`，参数较全。

**需求点**：

- [ ] **R2-1** 补充重排截断/阈值类参数（如 `RAG_RERANKER_TOP_N`、`RAG_RERANKER_MIN_SCORE`）。
- [ ] **R2-2** 支持更多重排 provider（本地其他 CrossEncoder、自定义 HTTP 重排服务）。
- [ ] **R2-3** 保持现有 `fail_open` 语义与 `rerank_comparison` Trace 结构不变。

**验收标准**：切换重排模式仅改配置；失败回退行为与 Trace 输出与现状一致。

### 4.3 融合算法（Fusion）

**目标**：混合检索的融合算法从硬编码 RRF 抽象为可插拔组件。

**现状**：`pipeline/fusion.py` 的 `reciprocal_rank_fusion` 被 `_hybrid_search` 直接调用，无契约、无配置（仅 `rrf_rank_constant`）。

**需求点**：

- [ ] **R3-1** 新增 `Fusion(ABC)` 契约：`fuse(result_sets: dict[str, list[RetrievedChunk]], *, top_k: int) -> list[RetrievedChunk]`。
- [ ] **R3-2** 提供默认实现：`RRF`（保留）、加权和 `WeightedSum`、`ReciprocalScoreFusion`。`WeightedSum` 必须配置明确的分数归一化方法，禁止直接混合不可比分数。
- [ ] **R3-3** 新增配置项 `RAG_FUSION_MODE`（`rrf` 默认 / `weighted_sum` / `rrs`），参数 `RAG_FUSION_RANK_CONSTANT`（替代 `RRF_RANK_CONSTANT`，旧键保留别名）、`RAG_FUSION_WEIGHTS`。
- [ ] **R3-4** `AdaptiveRetriever` 通过工厂注入 `Fusion` 实现。

**验收标准**：

1. 切换融合算法仅改配置，`_hybrid_search` 不依赖具体融合函数。
2. 不同分数体系下融合结果不假设分数可比（沿用现有注释约束）。
3. `WeightedSum` 的归一化方式、权重和最终贡献写入 Trace。

### 4.4 KeywordStore

**目标**：关键词检索后端保持可配置、可替换。

**现状**：已支持 `memory | elasticsearch`，含 ES 不可用自动回退。

**需求点**：

- [ ] **R4-1** 补充 BM25 与分词参数配置（`k1`、`b`、`analyzer` 已部分支持，补齐中文分词器选择）。
- [ ] **R4-2**（可选）预留其他关键词后端（如 `redis` / 自研倒排）。

**验收标准**：切换关键词后端仅改配置；ES 不可用时回退内存 BM25 的行为保持不变。

---

## 5. 评估层

### 5.1 评估算法

**目标**：评估指标与评估流程可自定义。

**现状**：`RetrievalEvaluator` 输出重排前后指标，`RAGEvaluator` 用 `AnswerJudge` 打分；指标固定，不可扩展。

**需求点**：

- [ ] **E1-1** 分别定义检索指标与回答指标契约，避免用一个宽泛的 `Metric` 同时承载不同输入；提供 recall@k、MRR、NDCG、faithfulness、relevance 等内置实现。
- [ ] **E1-2** 指标选择配置化：`RAG_EVALUATION_METRICS`（逗号分隔指标名）。
- [ ] **E1-3** 评估输出统一为 `EvaluationReport` 结构，支持自定义指标写入 `metrics` 扩展字段。
- [ ] **E1-4** 评估流程（检索评估 / 端到端评估）保持现有入口，支持注入自定义评估器。

**验收标准**：

1. 用户注册自定义指标后，评估报告包含该指标。
2. 新增指标不改评估主流程。

---

## 6. 统一上层对话接口

**目标**：无论底层组件如何配置，对外暴露稳定的对话/检索接口，使「验证通过的配置」可导出为定制化 RAG 服务。

**需求点**：

- [ ] **C1-1** 稳定公开 API（保持不变）：`POST /v1/retrieve`、`POST /v1/chat`、`POST /v1/chat/stream`，与底层组件解耦。
- [ ] **C1-2** 统一服务构造入口 `build_service(settings) -> ServiceRuntime`：构建应用级共享组件及知识库运行时工厂，供 API 层与外部调用复用；不得绕过现有 `KnowledgeBaseManager` 再维护第二套装配逻辑。
- [ ] **C1-3** 预设（Preset）机制：将一组验证通过的非敏感配置保存为带 schema 版本的 JSON（YAML 可后续增加）；`RAG_SERVICE_PRESET` 指向预设文件。Preset 只记录密钥环境变量名，不保存密钥值。
- [ ] **C1-4** 配置快照与审计：`/health` 记录当前应用组件，检索 Trace 记录实际参与检索的组件，写入运行与知识库索引清单记录 Embedder/Chunker，评估报告保存脱敏配置快照。

**验收标准**：

1. 同一份配置在不同环境启动得到一致的检索/回答行为。
2. 用预设启动即可获得定制化服务，无需重写 API 层。
3. 导出的预设和配置快照不包含密钥，可完成 schema 校验和导入导出 round-trip。

---

## 7. 配置体系

**目标**：所有组件选择与参数收敛到统一的 `Settings`，校验与降级语义一致。

**需求点**：

- [ ] **CF-1** 所有新增配置遵循 `RAG_` 前缀与 pydantic-settings 约定，集中于 `config.py`。
- [ ] **CF-2** 只有可选组件提供 `disabled`；只有允许安全降级的组件提供 `auto`。Embedder、VectorStore、Chunker 等核心组件必须选择具体实现，且持久化索引存在时禁止跨实现静默降级。
- [ ] **CF-3** 配置校验：`Literal`/范围校验在启动时进行；非法配置 fail-fast（类似 `llm` 模式）或降级（类似 `auto` 模式）需在组件契约中明确。
- [ ] **CF-4** `/health` 统一暴露每个组件的 `configured` vs `active` 与 `fallback_reason`。

---

## 8. 非功能需求

- [ ] **N1 可观测**：按组件实际参与阶段记录信息——检索组件进入 Trace，写入组件进入 ingestion run/索引清单，应用级组件进入 `/health`，评估所用配置进入报告快照。
- [ ] **N2 回退安全**：任一可选组件不可用时降级，不中断主链路；核心组件不可用时给出明确错误。
- [ ] **N3 向后兼容**：现有配置键（如 `RAG_RRF_RANK_CONSTANT`）保留为别名；现有 API 与 Trace 结构不破坏。
- [ ] **N4 测试**：每个新契约提供「模拟实现」的契约测试；每个工厂提供配置矩阵测试（各 mode 的构建/降级路径）。
- [ ] **N5 文档**：每新增组件更新 `.env.example` 与 README 对应章节。

---

## 9. 实施优先级（分期）

| 阶段 | 内容 | 关键组件 |
|---|---|---|
| **P0-A（基线与统一装配）** | 固化当前基线；引入 `ServiceRuntime` 和知识库运行时工厂；统一组件运行信息；消除 API 全局硬编码与重复装配 | Service、KnowledgeBaseRuntime、配置模型 |
| **P0-B（低风险契约补全）** | 补 `Chunker`、`Fusion` 契约与工厂；分块参数配置化；Planner disabled；RRF 保持默认 | Chunker、Fusion、QueryPlanner |
| **P1（索引安全与核心工厂）** | Embedder/VectorStore 工厂；索引指纹；显式重建门禁；生命周期能力契约 | Embedder、VectorStore、IndexManifest |
| **P2（预设与可观测）** | 版本化 Preset；脱敏配置快照；组件 configured/active/fallback 统一展示 | Preset、Health、Trace、EvaluationReport |
| **P3（生态扩展）** | 更多 adapter、嵌入/向量后端；可插拔评估指标；额外融合和重排实现 | SourceAdapter、Metric、各后端 |

---

## 10. 风险与开放问题

| 风险 / 问题 | 说明 | 建议 |
|---|---|---|
| 嵌入维度切换 | 更换嵌入模型导致维度与存量向量不符 | 强制校验 + 提供重建索引工具 |
| 配置生效时机 | 热更新 vs 重启生效 | 初版统一为**重启生效**，避免状态不一致 |
| 向量库迁移 | 切换后端后存量数据不可用 | 提供基于 `Document` 重建索引的迁移脚本 |
| 多知识库运行时 | 已实现知识库隔离，组件工厂若忽略该层会造成重复装配或配置不一致 | 纳入本迭代；多租户认证与分布式权限仍不纳入 |
| 组件命名一致性 | `planner`/`router` 等历史命名混用 | 新契约统一为 `*Planner`，旧名保留别名 |
| 自动降级污染索引 | Embedder 变化即使维度相同也可能让既有向量失效 | 保存索引指纹；非空知识库 fail-closed；通过显式重建迁移 |
| Preset 泄露密钥 | 直接序列化 Settings 可能包含 API Key | 导出白名单字段并只记录密钥环境变量名 |
| 插件动态加载 | 任意 Python 导入路径可能执行不可信代码 | 初版面向本地可信扩展，优先使用 Python entry points，并在文档中声明信任边界 |

---

## 11. 附录：契约/配置命名约定速查

- 算法契约集中在 `contracts/providers.py`（新增 `Chunker`、`Fusion`）；存储管理能力可放在独立 lifecycle/contracts 模块，避免扩大 Pipeline 的依赖面。
- 工厂命名 `build_<component>(settings)`，置于 `providers/` 下对应模块。
- 注册表命名 `XxxRegistry`，提供 `register` / `get`。
- 配置键命名 `RAG_<COMPONENT>_<PARAM>`；`disabled` 仅用于可选组件，`auto` 仅用于能够安全降级的组件。
- 详细实施顺序与进度记录规则见 `docs/implementation-plan.md`。
