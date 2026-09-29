# 实施进度

## 2026-09-29 · P3 第二批：PDF 文本层解析

- 状态：本批完成；P3 其他扩展待实施。
- 改动：PdfAdapter、PDF 上传入口与无文本页面提示；每页一个 Document，保留 page_number、page_count、title。
- 安全与边界：加密/损坏/纯扫描文件拒绝；10 MB、500 页、单页内容流 5 MB、正文 200 万字符限制。不执行脚本或抓取链接，不含 OCR；尚无进程级硬资源隔离，仅面向本地可信文件。
- 兼容性：新增 pypdf 依赖（测试版本 6.19.0）；既有格式和知识库不变，未重启服务或修改用户数据。
- 验证：140 passed、4 skipped；Ruff 和 JavaScript 语法检查通过；覆盖 PDF 文本/空白页、元数据、损坏/加密、限额以及 API 归档、去重、重启重建。测试使用临时数据和模拟索引，无收费模型调用。
- 下一步：HTML 文件解析；URL Connector 的 SSRF 等边界独立处理。

## 2026-09-29 · P3 第一批：CSV / Markdown

- 状态：本批完成；P3 其余扩展待实施。
- 改动：注册 CSV 与 Markdown Adapter，UI 增加格式入口，复用字段勾选、预览、入库、归档和重建。
- CSV：UTF-8 表头校验、引号/多行解析，字段选择及字符串 raw_metadata。
- Markdown：标题层级、正文行号、围栏代码保护；边界见 source-formats.md。
- 兼容性：不修改原有格式，不迁移或清空知识库；同文件以不同格式导入属于不同 Document。
- 验证：131 passed、4 skipped；新增 API 上传→预览→入库→重复跳过→重启→清空重建测试（临时目录、模拟索引）。Ruff 与前端 JavaScript 语法检查通过；未调用收费模型或修改运行中知识库。
- 下一步：上传式 PDF 文本解析；不包含 OCR。

## 2026-09-28 · P2 Preset 与脱敏审计

- 状态：完成。
- 改动：版本 1 JSON Preset、RAG_SERVICE_PRESET 加载、明确覆盖顺序、导出与校验 API、脱敏配置快照及稳定哈希。
- 评估：完整检索/RAG 报告增加 config_snapshot 和 knowledge_base_id；旧报告默认字段兼容。
- 安全：凭据只导出环境变量引用；拒绝含认证信息的 URL 导出；快照清理 URL 认证信息并移除已知凭据。
- 验证：118 passed、4 skipped；覆盖往返、优先级、自定义密钥引用、非法版本/字段、URL 和密钥脱敏、报告快照。
- 边界：不热更新、不写用户 .env、不执行真实 Provider 调用；config_hash 仅标识脱敏配置，不能保证模型输出完全相同。
- 下一步：P3，优先 CSV 与结构化 Markdown Adapter。

## 2026-09-28 · P1 嵌入/向量工厂与索引安全

- 状态：完成。
- 基线：6f703a7，提交 P0-A/P0-B。
- 改动：Embedding/VectorStore 注册工厂、compatible HTTP Embedder、生命周期协议、SQLite 索引清单与规范 Document 恢复档案、受保护的写入/检索/重建。
- 兼容性：默认 Hash/Chroma 不变；已有无指纹非空索引需显式重建。重建失败阻断查询/写入；不自动清空或认领用户数据。受管理的 ES 写入严格检查主索引成功。
- UI：展示索引阻断原因，重建失败明确提示，避免误报成功。
- 验证：108 passed、4 skipped；测试使用本地 Hash、临时 Chroma 和模拟远程接口，不产生远程模型费用。
- 下一步：P2 的版本化 Preset 与脱敏配置审计。
- 边界：单进程原地重建，失败后可重试恢复但无自动回滚；无原始来源的旧直写索引不能自动重建。详见 index-safety.md。

## 2026-09-27 · P0-B 算法契约与配置

- 状态：完成（本阶段交付 RRF，WeightedSum/RRS 留在 P3）。
- 改动：新增 Chunker/Fusion 契约与可信进程内注册表、工厂；统一服务注入分块器和融合器；Planner disabled 返回固定计划且不调用 LLM。
- 配置：分块模式、大小、重叠；融合模式与新 rank constant；固定检索策略与独立重排开关。旧 RRF 键继续生效，新键显式配置时优先，冲突在健康检查中可见。
- 兼容性：默认 800/120、RRF=60 不变；保留旧 RRF 函数、构造参数和 rrf_fusion Trace 步骤。自定义分块器无需提供 chunk_size/overlap 属性。
- 验证：92 passed、4 skipped；新增模拟组件从注册、装配、来源入库到混合检索的端到端用例，以及三种固定策略、非法配置和新旧配置优先级测试。
- 边界：参数修改不会自动重建历史索引；本阶段未修改 .env 或现有数据；配置重启生效。
- 下一步：P1 的 Embedder/VectorStore 工厂、IndexManifest 及索引兼容校验。

### P3 WeightedSum 归一化设计约束

按召回通道独立执行 min-max 归一化后加权，空通道无贡献，缺失候选贡献为零；
非空通道分数全部相同时归一化为 1，权重须非负且总和大于零，输出按总分及稳定 ID 排序。
Trace 需保留原始分数、归一化分数和各通道加权贡献。该协议待 P3 实现与数据集验证。

## 2026-09-27 · P0-A 统一服务装配

- 状态：完成。
- 基线提交：3555dfb，包含知识源、多知识库、开发者控制台与迭代计划。
- 改动：新增 service.py 的 build_service、ServiceRuntime、ComponentInfo；默认库与新增库复用同一个装配工厂；API 通过服务获取评估器并统一关闭资源。
- 兼容性：保留原有路由、健康检查字段、默认 collection/index/source 目录；新增 components 是启动时组件选择信息，逐请求降级仍由 Trace 描述。
- 配置：增加 RAG_SOURCE_DIRECTORY、RAG_KNOWLEDGE_BASE_DIRECTORY，默认路径不变。
- 验证：87 passed、4 skipped；新增真实 Chroma 双库隔离、共享组件和幂等关闭测试。未执行远程收费 Provider 测试。
- 下一步：P0-B 的 Chunker/Fusion 契约、工厂与 Planner disabled。
- 边界：保留 API 模块默认服务实例与兼容别名；尚未提供动态热更新或 IndexManifest，这些属于后续阶段。
