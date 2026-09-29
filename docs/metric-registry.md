# 指标注册表（兼容扩展层）

`RAG_EVALUATION_METRICS` 使用逗号分隔名称，默认为空。配置后重启，未知名称启动失败；不执行任意配置中的 Python 代码。Preset 与配置快照自动包含该字段。

内置检索名称：`retrieval.hit_rate`、`retrieval.precision_at_k`、`retrieval.recall_at_k`、`retrieval.mrr`、`retrieval.ndcg_at_k`。

内置回答名称：`answer.groundedness`、`answer.answer_relevancy`、`answer.citation_validity`、`answer.citation_correctness`、`answer.citation_precision`、`answer.citation_recall`、`answer.reference_similarity`。

完整报告和单条结果新增 `metric_extensions`：检索指标输出 `.before` / `.after` / `.delta`；回答输出单个得分。聚合为可用数值的算术均值，全缺失为 null，不把缺失当作零。插件异常使当前用例失败，其他用例继续；错误仅记录异常类型。

为兼容旧 API/UI，本批保留并继续计算原固定指标，不通过该配置关闭旧指标或 LLM 裁判。报告列表摘要及 UI 固定卡片仍只展示旧字段，扩展分数通过完整报告 JSON 获取。纯检索评估只运行选中的检索指标，忽略回答指标。

回答内置指标复用当前 Judge 结果，不额外调用模型；heuristic_v1 的 groundedness 是词汇覆盖近似，不能当作经过验证的语义 faithfulness。LLM 裁判和回退标志仍由 answer_metrics.method/fallback_used 表达。

## Python 扩展

在 build_service 之前注册；可直接给评估器构造参数传入 `metrics` 字符串。

```python
from rag_framework.evaluation.registry import retrieval_metrics, RetrievalMetricInput

def first_hit(context: RetrievalMetricInput) -> float:
    return float(bool(context.retrieved_ids) and context.retrieved_ids[0] in context.relevant_ids)

retrieval_metrics.register('retrieval.first_hit', first_hit)
```

回答注册到 `answer_metrics`，输入为独立的 `AnswerMetricInput(case, response, judged_metrics)`。函数同步、只读、快速执行，返回 [0,1] 有限数值或 None；禁止重复注册，不允许覆盖内置项。使用对应 retrieval./answer. 前缀避免跨表重名。注册表是进程级启动扩展点，不支持请求期间热注册；不应在指标内进行耗时网络调用。

自定义插件的版本目前需由部署代码版本追踪；配置哈希记录名称，但不计算函数实现哈希。后续可完善插件元数据、异步指标和 UI 动态展示。
