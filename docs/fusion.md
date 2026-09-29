# WeightedSum 融合

配置 `RAG_FUSION_MODE=weighted_sum`，`RAG_FUSION_NORMALIZATION=min_max`，
`RAG_FUSION_WEIGHTS={"vector":0.5,"keyword":0.5}` 后重启。默认仍为 RRF。

每路假设分数越高越相关，先按 Chunk ID 去重（取最高分），再计算
`normalized=(score-min)/(max-min)`；只有一个候选或全同分时归一值为 1。
最终分数为每路 `weight * normalized` 之和；未召回贡献为 0。
不同路权重不自动归一，未配置的路权重为 1，权重为 0 的路完全排除。
空路跳过，所有路禁用时返回空结果；负权重、非有限权重/分数拒绝。
同分按 Chunk ID 排序，确保稳定；不修改原始结果。

支持负原始分（例如 cosine），但不直接混合不同 Provider 原始分数。
min-max 对极值与候选集大小敏感，候选最小分归一后为 0；该分数不是概率。
建议通过同一测试集比较 RRF 和 WeightedSum，而非仅比较原始分值。

现有混合检索 Trace 保存实现、权重与归一规则；候选 component_scores 保存
每路原分、`:normalized`、`:contribution` 及 `weighted_sum` 总分。
不改变索引指纹，不需要重建，配置快照哈希会变化。

本批只交付 WeightedSum。RRS 的公式/分数方向尚未定义，不以猜测实现；
额外重排 Provider 待确定目标协议。现有 RRF、云端与本地重排保持不变。
