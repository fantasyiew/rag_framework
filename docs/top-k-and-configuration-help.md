# 检索上限与配置参数说明

配置键继续使用 default_top_k（RAG_DEFAULT_TOP_K），UI 展示为 top_k（检索硬上限）。
正整数 1～100 是最终检索结果的硬上限；null、留空或 0 表示不额外限制，由规划器决定。
环境变量也可设置为空字符串。旧配置中的正整数自动采用新的硬上限语义。

effective_top_k = min(planned_top_k, configured_limit)，无上限时直接使用 planned_top_k。
该限制统一作用于所有策略、改写查询合并结果及重排后的最终上下文。
候选召回预算和 reranker_candidate_k 可超过硬上限，以保持重排质量。
Trace 的 select_retrieval_strategy 记录 planned_top_k、top_k_limit、effective_top_k，
plan.decision.top_k 保存本次有效值。

不额外限制不意味着取出整个知识库：规划器本身仍决定有限 top_k（当前协议 1～100）。
固定或规则规划在未设置上限时默认选取 8；模型失败降级时同样采用该基线。
context_count = min(实际 final_context 数量, generation_max_context_chunks)。
因此 top_k 为 6 时生成 context_count 不会超过 6，但可以因结果不足或生成限制更小而降低。

配置工作台每个参数名称右侧提供问号按钮；鼠标悬浮或键盘聚焦展示用途、
取值约束、默认值、环境变量和生效方式。详情来自后端配置 schema。
top_k 支持应用并持久化；代码首次部署仍需重启加载新版本，之后该参数无需重启。
