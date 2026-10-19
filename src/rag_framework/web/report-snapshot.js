// Historical reports must never substitute the current workbench configuration.
export function snapshotRows(report) {
  const snapshot = report.config_snapshot;
  if (!snapshot) return null;
  const s = snapshot.settings || {}, e = snapshot.evaluation || {};
  const embedding = snapshot.embedding_binding?.settings || s;
  const active = snapshot.components || {};
  const value = v => v === null || v === undefined ? '未设置' : typeof v === 'object' ? JSON.stringify(v) : String(v);
  return [
    ['快照 ID', snapshot.snapshot_id || '旧版快照（无独立 ID）'],
    ['配置版本', value(snapshot.config_version)],
    ['采集时间', snapshot.captured_at ? new Date(snapshot.captured_at * 1000).toLocaleString() : '旧版未记录'],
    ['知识库', value(e.knowledge_base_id || snapshot.knowledge_base_id || report.knowledge_base_id)],
    ['测试集 ID', value(e.dataset_id || report.dataset_id)],
    ['评估类型 / K', `${e.kind || report.kind} / ${e.k ?? report.k}`],
    ['规划模式（配置 / 构建时生效）', `${value(s.query_planner_mode)} / ${value(active.planner?.active)}`],
    ['固定策略 / 重排开关（disabled 时使用）', `${value(s.default_retrieval_strategy)} / ${value(s.default_retrieval_rerank)}`],
    ['检索 top_k 硬上限', s.default_top_k === null || s.default_top_k === 0 ? '不限上限，由规划器决定' : value(s.default_top_k)],
    ['生成上下文上限', value(s.generation_max_context_chunks)],
    ['融合方式', value(s.fusion_mode)],
    ['重排模式 / 云端模型', `${value(s.reranker_mode)} / ${value(s.reranker_cloud_model)}`],
    ['嵌入模式 / 模型 / 维度', `${value(embedding.embedding_mode)} / ${value(embedding.embedding_model)} / ${value(embedding.embedding_dimensions)}`],
    ['生成模式 / 模型', `${value(s.answer_generator_mode)} / ${value(s.generation_model || s.planner_model)}`],
    ['裁判模式 / 模型', `${value(s.evaluation_judge_mode)} / ${value(s.evaluation_judge_model || s.generation_model || s.planner_model)}`],
    ['并发数', value(e.concurrency ?? s.evaluation_concurrency)],
    ['全局配置摘要', value(snapshot.config_hash)],
    ['本次完整快照摘要', value(snapshot.snapshot_hash)],
  ];
}

export function appendReportSnapshot({report, target, el, table, details}) {
  const rows = snapshotRows(report);
  if (!rows) {
    target.append(el('p', '此历史报告未保存配置快照，无法准确还原当时配置；不会使用当前配置替代。', 'muted'));
    return;
  }
  const panel = el('details', undefined, 'panel pad');
  panel.append(el('summary', '本次评估配置（点击展开）'),
    el('p', '以下为运行时历史快照，不随工作台后续修改而变化。构建时生效模式不代表每条用例均未发生降级，具体情况请看 Trace。', 'muted'),
    table(['配置项', '快照值'], rows), details('完整配置快照（含提示词、嵌入绑定和索引身份）', report.config_snapshot));
  target.append(panel);
}
