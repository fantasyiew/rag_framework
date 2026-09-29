# 变更记录

## 2026-09-29 · P3 WeightedSum

- 新增 weighted_sum 融合模式，支持 JSON 权重配置及 min_max 归一化。
- 候选 component_scores 保存原始分、归一分和贡献；Trace 复用融合参数记录。
- 默认 RRF、现有重排与索引保持不变；使用规则见 fusion.md。
- RRS 与其他重排 Provider 尚未实现，需先明确公式与协议。

## 2026-09-29 · P3 指标注册表

- 检索与回答指标采用独立输入契约，支持启动时注册同步自定义指标。
- 新增 RAG_EVALUATION_METRICS，完整报告/用例新增 metric_extensions；保留原固定指标和 UI。
- 扩展分数验证范围与有限值；缺失参考答案为 null，插件失败按用例隔离。
- 使用与本批兼容边界见 metric-registry.md。

## 2026-09-29 · P3 Qdrant

- 新增可选 Qdrant 本地向量后端、独立持久化目录与集合配置。
- 支持预计算向量写入、cosine 检索、等值过滤、统计、清空、健康检查和关闭。
- 多知识库使用独立子目录；索引指纹记录所选后端真实目录，切换时要求重建。
- 默认 Chroma 不变，未迁移现有数据；安装与限制见 qdrant.md。

## 2026-09-29 · P3 本地嵌入

- 增加 sentence_transformers 嵌入模式与 embedding 可选依赖。
- 默认 CPU、本地缓存、禁用远程代码；首次使用加载模型，失败不静默降级。
- 可配置归一化和查询/文档前缀，并记录到索引指纹；切换模型或语义参数后需重建。
- 配置示例与限制见 local-embeddings.md；未更改用户 .env 或现有知识库。

## 2026-09-29 · P3 HTML 文件

- 新增 kind=html 与 UI 上传入口，按 h1–h6 分节，保留页面标题、标题路径和章节序号。
- 过滤脚本、样式等内容；不执行代码、不渲染 HTML、不加载外部资源。
- 无新增依赖，不改动存量来源或知识库；复用预览、去重、归档与重建。
- 仅支持 UTF-8 文件，不含 URL 抓取；解析边界见 source-formats.md。

## 2026-09-29 · P3 PDF

- 新增 kind=pdf 和 UI 入口，按页提取文本并记录页码、总页数、文档标题。
- 混合 PDF 跳过无文本页并提示页码；纯扫描、加密或损坏文件返回可读错误。
- 新增 pypdf>=6.18.1,<7.0.0；部署需更新依赖后重启服务。未清空或迁移已有知识库。
- 解析限额与本地可信文件边界见 source-formats.md；不支持 OCR 或表格结构恢复。

## 2026-09-29 · P3 CSV / Markdown

- 新增 kind=csv：勾选正文字段，其余列作为字符串 raw_metadata，校验表头与行列数。
- 新增 kind=markdown：按标题分节，记录标题路径和正文行号，保护围栏代码中的标题符号。
- UI 增加 CSV、Markdown 格式及上传扩展名；沿用原件归档、去重、写入历史与重建流程。
- 无新增依赖，无配置或数据迁移；旧 Markdown 按 text 导入的记录不自动转换。
- 使用与限制见 source-formats.md。

## 2026-09-28 · P2

- 新增版本化 Preset 加载与导出，密钥使用系统环境变量引用。
- 增加 /v1/config/preset、/v1/config/preset/validate、/v1/config/snapshot。
- /health 增加配置哈希；完整评估报告保存脱敏快照和知识库 ID。
- 增加 docs/presets.md，说明覆盖规则、导出约束和重启生效边界。

## 2026-09-28 · P1

- 提交 P0-A/P0-B 基线：6f703a7。
- 新增嵌入与向量后端工厂、可配置的兼容协议远程嵌入。
- 索引身份记录模型/维度/分块/后端；不匹配返回 409，禁止跨模型静默降级。
- 新增规范 Document 恢复档案，显式重建后原子发布成功指纹。
- 重建失败保留可恢复输入，阻断半成品索引；Chroma 清空重置集合维度。
- 健康检查和知识库管理增加索引状态，UI 不再把失败重建显示为成功。
- 新增配置示例和 index-safety.md；部署仍限制单 worker。

## 2026-09-27 · P0-B

- Chunker/Fusion 提供抽象接口与注册工厂，新增实现无需修改管线。
- 默认分块参数可配置；写入记录增加 chunker 和 chunker_parameters。
- 融合通过注入执行；默认 RRF 保持旧行为，并在 Trace 中展示实现与参数。
- Planner 增加 disabled：固定 vector/keyword/hybrid，无模型分析及改写，可独立控制重排。
- 新融合配置键优先于旧 RRF 键；默认配置无需迁移。
- 验证：92 个测试通过、4 个环境测试跳过。

## 2026-09-27 · P0-A

- 提交当前功能基线 3555dfb。
- 新增可供 Python 调用的 build_service(settings)，统一知识库运行时、共享模型、评估器和资源关闭。
- /health 新增 components：configured、active、implementation、parameters、fallback_reason；仅输出显式选择的非敏感字段。
- 新增 RAG_SOURCE_DIRECTORY 与 RAG_KNOWLEDGE_BASE_DIRECTORY；无需迁移已有数据。
- 新增双知识库索引隔离与服务关闭回归测试。
