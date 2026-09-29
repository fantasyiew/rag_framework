# 本地 sentence-transformers 嵌入

安装可选依赖：`pip install -e ".[embedding]"`。本批不自动安装 Torch 或下载模型。

配置示例（必须根据实际模型填写名称和维度）：

```dotenv
RAG_EMBEDDING_MODE=sentence_transformers
RAG_EMBEDDING_MODEL=D:/models/your-sentence-transformer
RAG_EMBEDDING_DIMENSIONS=384
RAG_EMBEDDING_DEVICE=cpu
RAG_EMBEDDING_LOCAL_FILES_ONLY=true
RAG_EMBEDDING_NORMALIZE=true
RAG_EMBEDDING_BATCH_SIZE=10
RAG_EMBEDDING_QUERY_PREFIX=
RAG_EMBEDDING_DOCUMENT_PREFIX=
# RAG_EMBEDDING_MODEL_REVISION=immutable-model-version
```

- 首次嵌入才加载模型；启动成功或 health 中的 active 不代表本地模型已经加载验证。请用临时知识库先试写入及查询。
- 默认仅使用缓存/本地文件。显式设置 local_files_only=false 才允许库下载模型。始终禁用 trust_remote_code，加载来自可信来源的模型。
- 使用标准 encode 接口及显式前缀，不采用模型默认 prompt，也不启用任务路由。需要特殊 query/document 路由的模型不在本批支持范围；前缀需参考所选模型说明。
- 在后台线程串行执行推理，避免阻塞事件循环或同时加载同一模型。取消请求不会强制中断已经开始的线程推理。
- 维度、向量数量和有限数值均校验；依赖缺失、缓存缺失、设备不可用或推理失败均报错，不回退到 Hash。
- 模型名称、revision、维度、归一化和前缀纳入索引指纹，变更需显式重建。device、batch_size 不改变指纹。默认 hash 与 auto 选择逻辑保持不变。
- 本地目录内容不计算权重哈希：替换同一路径下权重时必须更新 revision 并重建；远程模型建议固定不可变 revision。配置指纹不能保证跨设备逐位相同。
- 本批使用模拟模型做自动化验证，尚未下载并验收真实模型性能。

API 依据：[SentenceTransformer 官方文档](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)。
