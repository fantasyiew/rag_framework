# 变更记录

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
