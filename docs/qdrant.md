# Qdrant 本地后端

安装 `pip install -e ".[qdrant]"`，重启前配置：

```dotenv
RAG_VECTOR_BACKEND=qdrant
RAG_QDRANT_DIRECTORY=data/qdrant
RAG_QDRANT_COLLECTION=documents
```

默认仍为 Chroma。本批只支持 Qdrant 嵌入式本地持久化，不支持远程 URL、认证或多进程共享目录。每个逻辑集合使用集合名 SHA256 对应的独立子目录，知识库后缀仍由统一运行时生成；清空只删除当前集合，不删除其他知识库目录。

框架生成向量；Qdrant 不加载模型。任意 Chunk ID 映射为稳定 UUID，完整 Chunk 保存在 payload，返回时恢复原 ID 与元数据。检索返回原生 cosine 相似度（可能为负），不是 Chroma 的距离变换分数；不要直接跨后端比较原始分数，默认 RRF 融合使用排名。

过滤仅支持平铺 metadata 字段的字符串/整数/布尔等值，多个字段为 AND。不支持浮点、范围、嵌套路径、逻辑运算或 Chroma 操作符，遇到不支持的表达式明确报错。元数据本身仍可完整保存。

切换后端、目录或集合会改变 IndexManifest 指纹，已有知识库将阻止写入/查询，需显式重建。旧 Chroma 数据不会自动迁移或删除，规范 Document 与来源档案仍用于重建。首次写入建立维度固定的集合，清空后可按新配置重建。使用单 worker，并正常关闭服务释放本地文件锁。

测试使用真实 qdrant-client 1.19.1 的临时本地目录，覆盖持久化、重开、重复写入、过滤、清空和双知识库隔离。不代表已验收生产规模性能或远程集群。

参考：[Qdrant Python 客户端本地模式](https://github.com/qdrant/qdrant-client)。
