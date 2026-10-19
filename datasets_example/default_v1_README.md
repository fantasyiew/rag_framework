# 默认知识库测试集 v1（2026-10-18）

- default_tuning_v1.jsonl：70 条调优用例。
- default_holdout_v1.jsonl：30 条留出用例；使用前可审核标签，但不要依据其评估结果反复调参。
- default_v1_manifest.json：来源快照、规模、分组与覆盖范围。

## 来源和边界

读取默认 Chroma documents 集合的 173 个实际 Chunk，本地服务当时未启动，采用 SQLite 只读模式读取；未创建/修改集合，未调用外部模型。精选 29 个结构化来源记录，按 document_id 分组。明显相关的记录（如高尾山/药王院、池上本门寺/御会式、新宿御苑不同介绍）放在同一侧。两个集合没有证据 Document 或 Chunk 交叉，但同属一个 JSON 原始来源文件，不能宣称源文件级或完全主题级隔离。

这是证据约束的人工智能辅助编写初版，不是独立人工审定的金标准。每条有 review_status；答案仅反映知识库快照，不代表景点开放状态、交通及价格的最新现实情况。

当前评估格式要求 relevant_chunk_ids 非空，因此暂不含无答案/拒答题；不能用虚构 ID 规避限制。后续需先扩展拒答评估契约，再独立加入该类用例。类型配比因现有能力调整，并非此前建议的六类固定比例。当前用例也未覆盖全部 173 个 Chunk 或全部知识主题。

## 元数据

metadata 保存 type、difficulty、split、answerable、knowledge_base_id、snapshot_hash、source_document_ids、source_record_indices、variant_group、required_evidence_groups、生成方式与审核状态。标准答案和元数据不会放入 query.text 或 filters；查询对象仅含问题和知识库 ID。

事实题与口语改写可能测试同一事实，variant_group 标记其关系；同一组不跨集合。汇总成绩存在关联样本，应同时观察分组表现，不能把 100 条视作完全独立样本。

required_evidence_groups 中每组表示一个必要的证据来源，组内 chunk_ids 为同文档匹配证据的候选替代；跨组通常需共同覆盖。当前评估器只使用扁平 relevant_chunk_ids，尚不会自动按组或类型统计。多证据题优先人工检查“必要证据是否真的缺一不可”。

相关证据标注只检查了种子和同文档原文片段匹配，未穷尽全库语义等价片段；保留 label_completeness 标记，避免宣称相关性标注完备。审核时需补充其他同样能回答问题的 Chunk，防止正确召回被误判。

## 使用

两份 JSONL 可分别通过测试集页面导入，名称使用 default_tuning_v1 和 default_holdout_v1。未自动导入，不改变已保存测试集。导入后选择 default 知识库运行检索或端到端评估。索引重建/替换后须核验 Chunk ID 和快照，不能直接沿用旧证据标注。

## 已完成校验

100 条均通过现有 JSONL 导入解析器；全部证据 ID 存在，必要证据引文与索引内容匹配，快照仍对应173个 Chunk。未发现重复问题或 ID，调优/留出集的证据 Document 无交叉。此检查不替代人工对答案完整性、歧义和全库相关性标注的审核。
