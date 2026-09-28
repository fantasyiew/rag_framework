# 变更记录

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
