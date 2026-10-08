// One expandable card per request; records survive refresh through the trace API.
export function initTraceHistory({el, target, api, renderTrace, notice}) {
  let conversationId = localStorage.getItem('ragConversationId') || crypto.randomUUID();
  localStorage.setItem('ragConversationId', conversationId);
  const cards = new Map();
  const toolbar = el('div', undefined, 'trace-lookup');
  const lookup = el('input'); lookup.placeholder = '输入 Trace ID 追溯';
  lookup.setAttribute('aria-label', '查找 Trace ID');
  const find = el('button', '查找'); find.type = 'button';
  toolbar.append(lookup, find); target.before(toolbar);
  const locate = (id, stepId) => {
    const card = cards.get(id);
    if (!card) return;
    card.open = true;
    const row = stepId ? [...card.querySelectorAll('[data-step-id]')].find(e => e.dataset.stepId === stepId) : card;
    if (stepId && row) row.querySelector('details').open = true;
    row?.scrollIntoView({block:'nearest', behavior:'smooth'});
    history.replaceState(null, '', '#trace=' + encodeURIComponent(id) + (stepId ? '&step=' + encodeURIComponent(stepId) : ''));
  };
  function start(query) {
    if (!cards.size) target.replaceChildren();
    cards.forEach(card => { card.open = false; });
    const card = el('details', undefined, 'trace-record'); card.open = true;
    const summary = el('summary', query + ' · 执行中…');
    const body = el('div', '正在执行查询分析、检索与生成…', 'trace-record-body');
    card.append(summary, body); target.append(card);
    return {card, summary, body, query};
  }
  function finish(handle, trace) {
    const {card, summary, body} = handle;
    const duration = trace.finished_at ? ((trace.finished_at - trace.started_at) * 1000).toFixed(0) + ' ms' : '未完成';
    const status = trace.status === 'failed' ? '失败' : trace.status === 'running' ? '执行未完成' : '完成';
    summary.textContent = trace.query.text + ' · ' + status + ' · ' + duration + ' · ' + trace.final_context.length + ' 个上下文';
    card.dataset.traceId = trace.id; cards.set(trace.id, card);
    renderTrace(trace, body);
    const id = el('p', 'Trace ID：' + trace.id, 'trace-id');
    const copy = el('button', '复制 ID'); copy.type = 'button';
    copy.onclick = async () => { try { await navigator.clipboard.writeText(trace.id); notice('Trace ID 已复制'); } catch { notice('请从 Trace ID 文本中手动复制'); } };
    id.append(copy); body.prepend(id);
    if (trace.knowledge_base_status === 'deleted' || trace.knowledge_base_status === 'archived') body.prepend(el('p', trace.knowledge_base_status === 'deleted' ? '来源知识库已删除；当前内容为保留的历史 Trace 快照。' : '来源知识库已弃用；当前内容为历史 Trace 快照。', 'error'));
    if (trace.error) body.prepend(el('p', '执行失败：' + trace.error + '。下方为已完成阶段。', 'error'));
  }
  async function load(id, stepId) {
    if (!cards.has(id)) {
      const record = await api('/v1/traces/' + encodeURIComponent(id));
      finish(start(record.trace.query.text), record.trace);
    }
    locate(id, stepId);
  }
  find.onclick = () => { const id = lookup.value.trim(); if (id) load(id).catch(e => notice(e.message, true)); };
  window.addEventListener('hashchange', () => {
    const anchor = new URLSearchParams(location.hash.slice(1));
    if (anchor.get('trace')) load(anchor.get('trace'), anchor.get('step')).catch(e => notice(e.message, true));
  });
  lookup.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); find.click(); } };
  return {
    get conversationId() { return conversationId; },
    start, finish,
    link(node, id) {
      const button = el('button', '查看对应 Trace ↗', 'trace-message-link'); button.type = 'button';
      button.onclick = () => load(id).catch(e => notice(e.message, true));
      node.append(button);
    },
    reset() {
      conversationId = crypto.randomUUID(); localStorage.setItem('ragConversationId', conversationId);
      cards.clear(); target.replaceChildren(el('p', '等待检索执行', 'muted'));
      history.replaceState(null, '', location.pathname);
    },
    async restore(onRecord) {
      const restoringConversation = conversationId;
      const records = await api('/v1/traces?conversation_id=' + encodeURIComponent(conversationId) + '&limit=500');
      if (conversationId !== restoringConversation) return;
      records.reverse().forEach(record => { const handle = start(record.trace.query.text); finish(handle, record.trace); onRecord(record); });
      const anchor = new URLSearchParams(location.hash.slice(1));
      if (anchor.get('trace')) await load(anchor.get('trace'), anchor.get('step'));
    }
  };
}
