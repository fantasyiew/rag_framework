# P1 索引身份、配置与恢复

日期：2026-09-28。状态：已实现。本次保持 .env 和已有知识库内容不变。

## 配置及扩展

- RAG_EMBEDDING_MODE：hash / compatible / auto，默认 hash。
- 远程模式必须显式设置 RAG_EMBEDDING_MODEL、RAG_EMBEDDING_API_KEY、RAG_EMBEDDING_BASE_URL。
- RAG_EMBEDDING_DIMENSIONS：预期维度，默认 384；远程模型应改为模型支持的维度。
- RAG_EMBEDDING_BATCH_SIZE：默认 10；RAG_EMBEDDING_REQUEST_TIMEOUT：默认 30 秒。
- RAG_EMBEDDING_SEND_DIMENSIONS：默认 true。不接受 dimensions 参数的兼容服务可设 false，但响应仍严格校验维度。
- RAG_EMBEDDING_MODEL_REVISION：可选部署/模型版本，变更后要求重建。
- RAG_VECTOR_BACKEND：默认 chroma，目前只内置此后端。

compatible 会向 BASE_URL 后追加 /embeddings，发送 model、input、encoding_format，
可选 dimensions。按响应 index 排序，检查数量、维度和有限数值。Provider 错误不输出
响应正文、输入文本或密钥，不回退 Hash。协议参考
[DashScope 同步向量接口](https://www.alibabacloud.com/help/en/model-studio/text-embedding-synchronous-api)。
请根据实际账户区域填写端点；本阶段未进行真实远程调用或费用测试。

可信 Python 扩展可注册 embedding_factory.embedders 和 vector_factory.vector_stores。
向量工厂要求 IndexAdmin、HealthCheck、AsyncClosable 能力；清空须允许下一次写入改变维度。
自定义 Embedder 应配置明确 model/revision，以保证部署身份可比较。

## 指纹与状态

每个来源目录下的 index-state.sqlite3 保存版本 1 索引清单及 canonical_documents。
指纹包含模型 Provider/实现类/模型名/版本/维度、端点摘要、分块器实现和参数、
向量后端及命名空间、关键词后端身份。密钥不参与存储。

状态为 empty（尚未初始化）、building、ready 或 failed；配置冲突在管理接口显示 blocked。
启动时检查全部已登记知识库并保留管理接口；默认库状态出现在 /health.index，
所有库状态出现在知识库详情。检索和写入每次重新校验；冲突返回 409 index_incompatible。

auto 仅作构建时选择：有嵌入凭据选 compatible，否则选 hash。
非空库始终受持久化指纹约束：若凭据移除导致选择 Hash，校验将阻止其查询/写入旧远程索引。
初始化或运行失败均不会切换模型。同维度不同模型也不兼容。

## 重建与恢复

1. 修改配置并重启后，先查看目标知识库状态。
2. 显式调用 POST /v1/knowledge-bases/{id}/rebuild，或在管理界面选择重建。
3. 预先解析成功写入记录对应的原始来源，合并规范 Document 档案及已有 Document 目录。
4. 将恢复输入和 building 状态写入 SQLite，再清理目标索引；Chroma 重建集合以重置固定维度。
5. 所有目标索引写入成功后，事务更新 ready 指纹；关键词主索引写入失败不会被内存回退掩盖。
6. 失败后保留原始文件、Document 档案、旧已生效指纹和失败状态；修复后重试重建。

这不是无停机的双索引切换，也不自动回滚已清理的索引。单进程操作锁防止查询读到
半成品；失败后必须显式重建才能恢复服务。查询会在写入/重建期间等待同一知识库锁。
跨进程或多 worker 不受此锁保护，暂不支持。

旧低层直写索引若没有 Document/原始来源，无法自动恢复；会拒绝空重建而保留原索引。
需补充原始来源并完成迁移准备，或明确清空后重新入库。不会自动认领旧索引为 Hash。
新低层直写会归档 Document，因此后续可恢复。

清空会删除派生索引和来源目录中的已索引 Document 列表，保留来源、历史和恢复档案。
切换后端后重建只操作新配置指定的索引，旧后端物理数据不自动删除。
Endpoint 摘要及路径标识用于兼容检查；并非密钥或模型内容。

## 验证范围

覆盖真实临时 Chroma 集合的维度迁移、同维不同模型、版本/分块变化、无指纹旧索引、
重建失败与重试、低层写入清空恢复、并发读写和远程 HTTP 模拟。
现有 Elasticsearch 外部集成测试仍按环境开关控制。
