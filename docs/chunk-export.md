# 知识库 Chunk 导出（2026-10-07）

知识库管理页“导出全部 Chunk”下载 ZIP，接口 GET /v1/knowledge-bases/{id}/export-chunks。

chunks.jsonl 每行一个实际向量索引中的 Chunk，保留 id、document_id、index、content、source_uri 和完整已存储 metadata。不重新解析源文件，不输出向量数组。由于索引分块会剔除 raw_metadata，导出按 document_id 从持久化 Document 记录补回该字段，保留原有编码；历史记录不存在时不伪造该字段。使用有界缓存避免全量加载 Document。

manifest.json 记录格式版本、知识库身份、导出时间、Chunk 数量、非敏感嵌入身份、索引 manifest 和 chunks 文件 SHA-256。不导出密钥或原始附件；这是分析快照，不是完整恢复备份。

Chroma 分页 get、Qdrant 分页 scroll 且 with_vectors=False，通过统一 VectorStore.iter_chunks 扩展能力接入。第三方后端可实现该方法，否则返回 501，不影响既有检索接口。

生成阶段持有管理操作、来源写入及索引锁；同一服务进程内阻止入库、重建、清空与模型切换。ZIP 写入临时文件，不将全量 Chunk 或压缩包加载到内存。完整生成后才发送响应，下载分段读取并清理临时文件。导出期间写操作可能等待；不保证绕过本服务的外部索引写入或多进程一致性。

原始 metadata 可能含用户自己的敏感业务信息，请谨慎分享导出包；服务配置密钥不纳入导出字段。此次未导出或修改用户实际知识库。

验证：5 项导出测试通过，覆盖两个后端分页、空库、非空库、知识库隔离、原始元数据补回、ZIP 校验及写锁等待。完整回归 252 项通过、4 项跳过。
