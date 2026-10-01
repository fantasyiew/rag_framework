# RAG Framework v0.2 实施计划

> 对应需求：`docs/iteration-requirements.md` v0.2.1  
> 创建日期：2026-09-27  
> 当前状态：P0-A、P0-B、P1、P2 已完成；P3 CSV / Markdown / PDF 文本解析已完成，其余待实施

## 1. 实施目标

在不破坏现有 API、知识库数据和 Trace 结构的前提下，将当前硬编码组件装配改造成配置驱动、可扩展且可审计的运行时。实施顺序优先解决统一装配和索引兼容，再增加具体 Provider，避免组件可切换但存量索引不可用。

## 2. 阶段与依赖

```text
P0-A 基线与统一装配
  └─ P0-B Chunker / Fusion / Planner 契约
       └─ P1 Embedder / VectorStore / IndexManifest
            └─ P2 Preset / 配置审计
                 └─ P3 Provider、Adapter、Metric 生态扩展
```

## 3. P0-A：基线与统一装配

### 任务

- [x] 提交并标记当前知识源、多知识库、评估与 UI 基线。
- [x] 定义 `ServiceRuntime`，集中持有应用级共享组件、评估存储和知识库管理器。
- [x] 定义知识库运行时工厂，统一创建索引、检索、生成和来源服务。
- [x] 将具体组件实例化从 `api/main.py` 移到 `build_service(settings)`。
- [x] 定义统一组件运行信息：`configured`、`active`、`implementation`、`parameters`、`fallback_reason`。
- [x] 保持现有路由、响应模型和默认配置兼容。

### 验收门槛

- API 层不直接实例化 Chroma、HashEmbedder、Chunker 或 KeywordStore。
- 默认知识库与新建知识库通过同一运行时工厂创建，只有 collection/index/source directory 命名不同。
- 原有测试全部通过，并新增双知识库隔离测试与运行时关闭测试。

## 4. P0-B：低风险契约与检索配置化

### 任务

- [x] 新增 `Chunker` 契约、注册表和 `build_chunker()`。
- [x] 配置化 `RAG_CHUNK_SIZE`、`RAG_CHUNK_OVERLAP`、`RAG_CHUNKER_MODE`。
- [x] 新增 `Fusion` 契约、注册表和 `build_fusion()`。
- [x] 将现有 RRF 封装为默认 Fusion 实现，保留旧配置键别名。
- [x] 为 WeightedSum 设计归一化协议；本阶段可只交付 RRF，避免仓促引入不可比分数。
- [x] 新增 Planner `disabled` 模式和固定检索策略，不执行自动 Query Rewrite。
- [x] 将 Chunker 参数记录到写入运行，将 Fusion 实现与参数记录到检索 Trace。

### 验收门槛

- 调整分块大小、重叠和融合模式只需修改配置。
- 自定义模拟 Chunker/Fusion 可通过注册表注入，Pipeline 不依赖具体实现。
- 旧 `RAG_RRF_RANK_CONSTANT` 仍可使用，冲突时新配置优先并产生可观测提示。
- 工厂配置矩阵、契约测试和现有端到端检索测试全部通过。

## 5. P1：索引安全与核心 Provider 工厂

### 任务

- [x] 实现 `build_embedder()`，首批支持 `hash` 与一个远程 OpenAI-compatible/DashScope 实现。
- [x] 实现 `build_vector_store()`，首批只正式支持 Chroma，同时预留注册表扩展点。
- [x] 定义 `IndexAdmin`、`HealthCheck`、`AsyncClosable` 等能力契约。
- [x] 新增知识库 `IndexManifest`，记录 Embedder 指纹、Chunker 指纹、创建时间和 schema 版本。
- [x] 在启动、写入、查询、重建前执行索引兼容校验。
- [x] 配置不兼容时阻止写入和查询，返回包含重建建议的可读错误。
- [x] 重建成功后原子更新索引清单；失败时保留可恢复状态和失败记录。

### 验收门槛

- 同维度但不同模型也能被识别为不兼容。
- 非空知识库不会因远程 Embedder 不可用而回退 Hash。
- 空知识库允许根据配置选定 Embedder，并在首次成功写入时固化指纹。
- 清空、重建和切换知识库继续可用，且不会清错 collection/index。

## 6. P2：Preset 与配置审计

### 任务

- [x] 定义版本化 Preset JSON schema。
- [x] 实现 Preset 加载、校验、导出和环境变量覆盖优先级。
- [x] API Key 只引用环境变量名，不写入 Preset、Trace、报告或日志。
- [x] `/health` 展示应用级组件的 configured/active/fallback。
- [x] 检索 Trace、ingestion run、IndexManifest 和评估报告分别保存其阶段相关配置。
- [x] 为配置快照增加稳定哈希，便于比较实验是否使用同一配置。

### 验收门槛

- Preset 导入导出 round-trip 后配置语义一致。
- 同一 Preset 与同一数据在相同依赖版本下可复现运行时组件选择。
- 自动化测试确认所有导出内容不包含 SecretStr 明文或已知测试密钥。

## 7. P3：生态扩展

### 建议顺序

1. CSV 与结构化 Markdown Adapter（已完成，边界见 source-formats.md）。
2. 上传式 PDF 文本解析（已完成）；OCR 作为独立可选能力，尚未实现。
3. HTML 文件解析（已完成）；URL 抓取作为独立 Connector（待实施），并加入 SSRF、重定向、大小和超时限制。
4. 本地 sentence-transformers（代码与模拟测试完成，真实模型待验收）与其他远程 Embedder（待扩展）。
5. 第二个 VectorStore 后端（Qdrant 本地模式已完成），用于验证契约是否真正解耦。
6. 检索指标和回答指标注册表（兼容扩展层已完成，动态 UI/异步插件待后续）。
7. WeightedSum（已完成）；RRS 与额外 Reranker Provider（公式/协议待确认，未实现）。

## 8. 测试策略

- 契约测试：每个契约用最小模拟实现验证 Pipeline 只依赖抽象接口。
- 工厂矩阵：覆盖具体模式、缺少配置、初始化失败、安全回退和 fail-closed。
- 数据安全：覆盖维度变化、同维不同模型、重建失败、清空后重建。
- 多知识库：覆盖 collection/index/source directory 隔离以及不同配置指纹。
- API 兼容：固定现有 OpenAPI 路由和关键响应字段。
- 安全测试：验证 Preset、健康检查、Trace、报告和日志不泄露密钥。
- 完整回归：每阶段结束运行 Ruff、Pytest、前端 JavaScript 语法检查与至少一次本地端到端烟雾测试。

## 9. 文档与进度记录规则

从下一次代码实现开始，每批代码改动必须同时更新 `docs/`：

- 本文档：勾选阶段任务并更新当前状态。
- `docs/implementation-progress.md`：记录日期、完成内容、测试证据、阻塞项和下一步。
- `docs/changes.md`：记录面向用户的行为变化、配置变化、迁移与兼容性影响。
- `docs/adr/`：仅用于无法从代码直接看出的重要架构决策。
- `.env.example` 与 `README.md`：新增或调整配置时同步更新。

单次任务完成的最低记录格式：

```markdown
## YYYY-MM-DD · 任务名称

- 状态：完成 / 部分完成 / 阻塞
- 改动：主要行为和关键文件
- 兼容性：API、配置、索引或数据迁移影响
- 验证：执行的测试及结果
- 下一步：后续任务或已知限制
```

代码、测试和对应文档应在同一提交中保持一致；未通过验收门槛时不得提前将阶段标记为完成。

## 10. 下一步执行建议

配置 UI 迭代：第一阶段动态表单、草稿校验和变更对比已完成（2026-10-01）；第二阶段为 Preset 导入、导出、保存及待重启状态；热更新留待后续评估。范围见 config-workbench.md。

WeightedSum 已完成。下一步确认 RRS 数学定义与额外重排协议，或优先开展真实模型和端到端验收；URL Connector 安全设计仍待单独处理。
