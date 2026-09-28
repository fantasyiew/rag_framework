const $ = (id) => document.getElementById(id);
const history = [];
let busy = false;
let reportRequest = 0;
let knowledgeBaseId = localStorage.getItem('knowledgeBaseId') || 'default';
const documentCache = new Map();
const kbPath = suffix => `/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}${suffix}`;
const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
};
function notice(text, error = false) {
  $('notice').textContent = text;
  $('notice').className = error ? 'error' : '';
  $('notice').hidden = !text;
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `请求失败 (${response.status})`);
  return data;
}
const post = (path, data) => api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
function details(title, data) {
  const node = el('details'); node.append(el('summary', title), el('pre', typeof data === 'string' ? data : JSON.stringify(data, null, 2))); return node;
}
function table(headers, rows) {
  const wrap = el('div', undefined, 'table-wrap'); const node = el('table'); const head = el('tr');
  headers.forEach(h => head.append(el('th', h))); node.append(head);
  rows.forEach(row => { const tr = el('tr'); row.forEach(value => { const cell = el('td'); if (value instanceof Node) cell.append(value); else cell.textContent = value ?? '—'; tr.append(cell); }); node.append(tr); });
  wrap.append(node); return wrap;
}
const score = value => typeof value === 'number' ? value.toFixed(3) : '—';
const previewText = value => value.length > 240 ? `${value.slice(0, 240)}…` : value;
async function copyText(value, button) {
  await navigator.clipboard.writeText(value);
  const label = button.textContent; button.textContent = '已复制'; setTimeout(() => { button.textContent = label; }, 1200);
}
function chunkButton(item, rankChange = null) {
  const button = el('button', item.chunk.id, 'chunk-link');
  button.type = 'button';
  button.title = previewText(item.chunk.content);
  button.setAttribute('aria-label', `查看 Chunk ${item.chunk.id} 的正文和元数据`);
  button.onclick = () => openChunkDetails(item, rankChange);
  return button;
}
async function openChunkDetails(item, rankChange = null) {
  const dialog = el('dialog', undefined, 'chunk-dialog');
  const head = el('div', undefined, 'dialog-head');
  const close = el('button', '关闭'); close.onclick = () => dialog.close();
  head.append(el('h2', 'Chunk 详情'), close);
  const body = el('div', undefined, 'dialog-body');
  const identity = el('div', undefined, 'dialog-grid');
  const fields = [
    ['Chunk ID', item.chunk.id], ['Document ID', item.chunk.document_id],
    ['Chunk 序号', item.chunk.index], ['召回来源', item.source],
    ['当前排名', item.rank], ['当前分数', score(item.score)],
    ['原始排名', rankChange?.original_rank], ['重排后排名', rankChange?.final_rank],
  ];
  fields.forEach(([name, value]) => { const row = el('div'); row.append(el('b', `${name}：`), document.createTextNode(value ?? '—')); identity.append(row); });
  const actions = el('div', undefined, 'dialog-actions');
  const copyId = el('button', '复制 Chunk ID'); copyId.onclick = () => copyText(item.chunk.id, copyId).catch(error => notice(error.message, true));
  const copyContent = el('button', '复制正文'); copyContent.onclick = () => copyText(item.chunk.content, copyContent).catch(error => notice(error.message, true));
  actions.append(copyId, copyContent);
  const content = el('section', undefined, 'dialog-section'); content.append(el('h3', 'Chunk 正文'), el('div', item.chunk.content, 'dialog-content'));
  const scores = el('section', undefined, 'dialog-section'); scores.append(el('h3', '检索与重排分数'), details('完整分数信息', {component_scores:item.component_scores, score:item.score, rank_change:rankChange})); scores.querySelector('details').open = true;
  const metadata = el('section', undefined, 'dialog-section'); metadata.append(el('h3', 'Chunk 元数据'), details('索引中的轻量元数据', item.chunk.metadata)); metadata.querySelector('details').open = true;
  const rawSection = el('section', undefined, 'dialog-section'); const rawStatus = el('p', '正在读取原始 Document…', 'dialog-message'); rawSection.append(el('h3', 'Document raw_metadata'), rawStatus);
  body.append(identity, actions, content, scores, metadata, rawSection); dialog.append(head, body); document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove(), {once:true}); dialog.showModal();
  const cacheKey = `${knowledgeBaseId}:${item.chunk.document_id}`;
  try {
    let documentData = documentCache.get(cacheKey);
    if (!documentData) { documentData = await api(kbPath(`/documents/${encodeURIComponent(item.chunk.document_id)}`)); documentCache.set(cacheKey, documentData); }
    rawStatus.replaceWith(details('完整原始元数据', documentData.metadata?.raw_metadata ?? {}));
    rawSection.querySelector('details').open = true;
  } catch (error) {
    rawStatus.textContent = `无法读取 raw_metadata：${error.message}。低层接口直接写入的文档可能没有来源目录记录。`;
  }
}
function showPage(page) {
  document.querySelectorAll('.page').forEach(node => node.hidden = node.id !== page);
  document.querySelectorAll('[data-page]').forEach(node => node.classList.toggle('active', node.dataset.page === page));
  $('breadcrumb').textContent = {playground:'检索工作台', datasets:'测试集', experiments:'实验报告', sources:'知识源', knowledge:'知识库管理'}[page];
  if (page === 'sources') loadSources().catch(error => notice(error.message, true));
  if (page === 'datasets') loadDatasets().catch(error => notice(error.message, true));
  if (page === 'experiments') loadReports().catch(error => notice(error.message, true));
}
document.querySelectorAll('[data-page]').forEach(node => node.onclick = () => showPage(node.dataset.page));
async function health() {
  try {
    const data = await api('/health');
    $('health').textContent = `${data.status === 'healthy' ? '● 服务在线' : '◐ 服务降级'} · ${data.configured_keyword_backend}\nJudge: ${data.active_evaluation_judge_mode}`;
    $('health').title = JSON.stringify(data, null, 2);
  } catch { $('health').textContent = '○ 服务不可用'; notice('无法连接服务，请检查后端是否启动。', true); }
}
$('refresh').onclick = health;
function renderTrace(trace, target = $('trace')) {
  target.replaceChildren();
  const stats = el('div', undefined, 'stat-row');
  [trace.plan?.decision?.strategy || '未记录策略', `${trace.candidates.length} 候选`, `${trace.final_context.length} 上下文`].forEach(text => stats.append(el('span', text, 'badge')));
  target.append(stats);
  if (trace.plan) target.append(details('Query 分析与检索决策', trace.plan));
  target.append(details('实际检索 Query', trace.retrieval_queries));
  const timeline = el('div');
  trace.steps.forEach(step => { const row = el('div', undefined, 'step'); row.append(el('b', step.name), el('span', `${step.duration_ms.toFixed(1)} ms`), details('阶段详情', step.details)); timeline.append(row); });
  target.append(timeline);
  if (trace.rerank_comparison) {
    const comparison = trace.rerank_comparison;
    const chunksById = new Map(trace.candidates.map(item => [item.chunk.id, item]));
    target.append(el('h3', '重排前后对比'));
    if (comparison.fallback_used) target.append(el('p', `发生回退：${comparison.fallback_reason}`, 'muted'));
    target.append(table(['Chunk', '原排名', '新排名', '重排分数'], comparison.changes.map(change => { const item = chunksById.get(change.chunk_id); return [item ? chunkButton(item, change) : change.chunk_id, change.original_rank, change.final_rank, score(change.rerank_score)]; })));
  }
  const chunks = el('details'); chunks.open = true; chunks.append(el('summary', '最终上下文'));
  trace.final_context.forEach(item => { const card = el('div', undefined, 'chunk'); card.append(chunkButton(item), el('p', item.chunk.content), details('来源、元数据与分数', item)); chunks.append(card); });
  if (!trace.final_context.length) chunks.append(el('p', '未找到相关内容。请确认已入库数据。', 'muted'));
  target.append(chunks, details('所有原始候选', trace.candidates), details('完整 Trace JSON', trace));
}
function message(role, text) {
  if ($('messages').querySelector('.empty')) $('messages').replaceChildren();
  const node = el('div', undefined, `message ${role}`); node.append(el('small', role === 'user' ? 'YOU' : 'ASSISTANT'), el('div', text)); $('messages').append(node); node.scrollIntoView({block:'nearest'}); return node;
}
$('chat-form').onsubmit = async event => {
  event.preventDefault(); if (busy) return;
  const query = $('query').value.trim(); if (!query) return;
  busy = true; $('send').disabled = true; $('clear').disabled = true;
  const mode = $('chat-mode').value; message('user', query); notice('正在执行检索' + (mode === 'chat' ? '与回答生成…' : '…'));
  try {
    const response = await post(`/v1/${mode}`, {text:query, knowledge_base_id:knowledgeBaseId, history:history.slice(-12)});
    const trace = mode === 'chat' ? response.retrieval : response;
    renderTrace(trace);
    const answer = mode === 'chat' ? response.answer.text : `召回 ${trace.candidates.length} 个候选，保留 ${trace.final_context.length} 个上下文。`;
    const node = message('assistant', answer);
    if (mode === 'chat') { node.append(details('引用证据', response.answer.citations)); history.push(`User: ${query}`, `Assistant: ${answer}`); }
    $('query').value = ''; notice('执行完成，可在右侧检查完整检索过程。');
  } catch (error) { message('assistant', `执行失败：${error.message}`); notice(error.message, true); }
  finally { busy = false; $('send').disabled = false; $('clear').disabled = false; }
};
$('clear').onclick = () => { if (busy) return; history.length = 0; $('messages').replaceChildren(el('div', '新对话已准备好。', 'empty')); $('trace').replaceChildren(el('div', '等待检索执行', 'empty')); };
async function formTask(event, task) {
  event.preventDefault(); const button = event.currentTarget.querySelector('button'); button.disabled = true;
  try { await task(); } catch (error) { notice(error.message, true); } finally { button.disabled = false; }
}
$('index-form').onsubmit = event => formTask(event, async () => {
  const content = $('document').value.trim(); if (!content) throw new Error('文档内容不能为空');
  notice('正在写入知识库…');
  const source = await api(`${kbPath('/sources')}?name=直接输入文本&kind=text`, {method:'POST', body:content});
  const result = await post(`${kbPath('/sources')}/${source.id}/ingest`, {});
  if (result.status === 'failed') throw new Error(`写入失败：${result.error}，可在知识源查看记录`);
  notice(`本次接收 ${result.received_documents} 篇，新增 ${result.created_documents} 篇，跳过 ${result.skipped_documents} 篇，新增 ${result.created_chunks} 个 chunk。`); $('document').value = '';
});
async function loadDatasets() {
  const datasets = await api('/v1/evaluation-datasets'); $('dataset-list').replaceChildren(); $('evaluation-dataset').replaceChildren();
  if (!datasets.length) $('dataset-list').append(el('p', '暂无测试集，请先导入 JSONL 文件。', 'muted'));
  datasets.forEach(data => {
    const card = el('div', undefined, 'item'); const link = el('a', '导出 JSONL ↗'); link.href = `/v1/evaluation-datasets/${encodeURIComponent(data.id)}/export`;
    card.append(el('strong', data.name), el('p', `${data.case_count} 个样例`, 'muted'), link);
    const preview = el('button', '查看样例'); preview.onclick = async () => { preview.disabled = true; try { const full = await api(`/v1/evaluation-datasets/${encodeURIComponent(data.id)}`); const detail = details('样例 JSON', full.cases); detail.open = true; card.append(detail); preview.remove(); } catch(error) { notice(error.message, true); preview.disabled = false; } }; card.append(preview);
    $('dataset-list').append(card); const option = el('option', data.name); option.value = data.id; $('evaluation-dataset').append(option);
  });
}
$('dataset-form').onsubmit = event => formTask(event, async () => {
  const file = $('dataset-file').files[0]; const name = $('dataset-name').value.trim(); if (!file || !name) throw new Error('请填写名称并选择 JSONL 文件');
  await api(`/v1/evaluation-datasets/import?name=${encodeURIComponent(name)}`, {method:'POST', headers:{'Content-Type':'application/x-ndjson'}, body:file});
  notice('测试集导入成功。'); await loadDatasets();
});
$('evaluation-form').onsubmit = event => formTask(event, async () => {
  const id = $('evaluation-dataset').value; if (!id) throw new Error('请先导入测试集');
  notice('评估运行中，请等待结果。');
  const report = await post(`/v1/evaluations/${$('evaluation-kind').value}/datasets/${encodeURIComponent(id)}`, {knowledge_base_id:knowledgeBaseId, k:Number($('evaluation-k').value), include_trace:true});
  showPage('experiments'); renderReport(report); notice(`评估结束：${report.successful_case_count}/${report.case_count} 个样例成功。`);
});
async function loadReports() {
  const reports = await api('/v1/evaluations'); $('report-list').replaceChildren();
  if (!reports.length) $('report-list').append(el('p', '暂无实验记录，从测试集页面开始评估。', 'muted'));
  reports.forEach(report => {
    const button = el('button', `${report.kind.toUpperCase()} · ${report.status}`, 'report-button'); button.append(el('small', `${new Date(report.started_at * 1000).toLocaleString()} · ${report.successful_case_count}/${report.case_count} 成功`));
    button.onclick = async () => { const request = ++reportRequest; try { const data = await api(`/v1/evaluations/${encodeURIComponent(report.id)}`); if (request === reportRequest) renderReport(data); } catch(error) { notice(error.message, true); } }; $('report-list').append(button);
  });
}
function renderReport(report) {
  const target = $('report-detail'); target.className = ''; target.replaceChildren(el('h2', `${report.kind.toUpperCase()} 评估结果`), el('p', `${report.status} · K=${report.k} · ${report.duration_ms.toFixed(0)} ms`, 'muted'));
  const metrics = report.metrics || report.retrieval_metrics;
  if (metrics) target.append(table(['检索指标', '重排前', '重排后', '变化'], Object.keys(metrics.before).map(key => [key, score(metrics.before[key]), score(metrics.after[key]), score(metrics.delta[key])])));
  if (report.answer_metrics) { target.append(el('h3', '回答质量'), details('评估方法与回退信息', report.answer_metrics)); target.append(table(['回答指标', '分数'], Object.entries(report.answer_metrics).filter(([,v]) => typeof v === 'number').map(([k,v]) => [k, score(v)]))); }
  report.cases.forEach(item => {
    const row = el('details'); row.append(el('summary', `${item.error ? '失败' : '完成'} · ${item.query}`));
    if (item.error) row.append(el('p', item.error));
    if (item.answer) row.append(el('p', item.answer.text));
    row.append(details('样例指标与结果', item));
    if (item.trace) { const trace = el('div', undefined, 'inspector'); renderTrace(item.trace, trace); row.append(trace); }
    target.append(row);
  });
}
$('reload-reports').onclick = () => loadReports().catch(error => notice(error.message, true));
health();

// Source workflow: inspect, configure, preview, then ingest the archived artifact.
let selectedSource = null;
const sourcesButton = el('button', '▧　知识源'); sourcesButton.dataset.page = 'sources';
sourcesButton.onclick = () => showPage('sources'); document.querySelector('nav').append(sourcesButton);
const sourcesPage = el('section', undefined, 'page'); sourcesPage.id = 'sources'; sourcesPage.hidden = true;
sourcesPage.innerHTML = `<div class="heading"><div><p class="eyebrow">KNOWLEDGE SOURCES</p><h1>把原始数据变成可检索的知识</h1><p>上传 → 选择字段 → 预览 Document → 入库</p></div></div>
<article class="panel pad"><form id="source-upload"><label>格式<select id="source-kind"><option value="text">纯文本 / Markdown（UTF-8）</option><option value="json">JSON 对象或对象数组</option><option value="docx">Word DOCX</option></select></label><label>文件<input id="source-file" type="file" accept=".txt,.md,.json,.docx" required></label><button class="primary">解析文件</button></form><p class="muted">上限 10 MB。JSON 暂不支持嵌套字段；DOCX 暂不处理图片和 OCR。</p><div id="source-options"></div><div id="source-preview"></div><button id="source-ingest" class="primary" hidden>确认入库</button></article><article class="panel pad"><h2>原始数据与写入记录</h2><button id="source-refresh">刷新记录</button><div id="source-records"></div></article>`;
document.querySelector('main').append(sourcesPage);
const sourceOptions = () => ({content_fields: Array.from($('source-options').querySelectorAll('input:checked')).map(node => node.value)});
$('source-upload').onsubmit = event => formTask(event, async () => {
  selectedSource = null; $('source-ingest').hidden = true; $('source-options').replaceChildren(); $('source-preview').replaceChildren();
  const file = $('source-file').files[0]; if (!file) throw new Error('请选择文件');
  selectedSource = await api(`${kbPath('/sources')}?name=${encodeURIComponent(file.name)}&kind=${$('source-kind').value}`, {method:'POST', body:file});
  const info = selectedSource.inspection;
  if (!info.supported) { notice(`${info.reason}：${info.nested_fields.join(', ')}`, true); await loadSources(); return; }
  if (info.fields) {
    $('source-options').append(el('p', '勾选正文内容字段；其余字段保存在 Document.metadata.raw_metadata。'));
    info.fields.forEach(field => { const label = el('label', `${field.name} · ${JSON.stringify(field.sample)}`); const input = el('input'); input.type = 'checkbox'; input.value = field.name; input.style.width = 'auto'; input.onchange = () => { $('source-ingest').hidden = true; $('source-preview').replaceChildren(); }; label.prepend(input); $('source-options').append(label); });
  }
  const preview = el('button', '预览 Document'); preview.onclick = async () => {
    preview.disabled = true; $('source-ingest').hidden = true;
    try { const data = await post(`${kbPath('/sources')}/${selectedSource.id}/preview`, sourceOptions()); $('source-preview').replaceChildren(el('p', `共 ${data.document_count} 篇，预览前 10 篇`), details('Document 正文与完整元数据', data.documents)); $('source-preview').querySelector('details').open = true; $('source-ingest').hidden = false; }
    catch(error) { notice(error.message, true); } finally { preview.disabled = false; }
  }; $('source-options').append(preview); notice('解析完成，请预览后确认入库。'); await loadSources();
});
$('source-ingest').onclick = async () => {
  $('source-ingest').disabled = true; $('source-upload').querySelector('button').disabled = true;
  try { const run = await post(`${kbPath('/sources')}/${selectedSource.id}/ingest`, sourceOptions()); notice(`状态 ${run.status}：新增 ${run.created_documents}，跳过 ${run.skipped_documents}，新增 chunk ${run.created_chunks}${run.error ? '，错误 '+run.error : ''}`, run.status === 'failed'); await loadSources(); }
  catch(error) { notice(error.message, true); } finally { $('source-ingest').disabled = false; $('source-upload').querySelector('button').disabled = false; }
};
async function loadSources() {
  const [sources, runs, documents] = await Promise.all([api(kbPath('/sources')), api(kbPath('/runs')), api(kbPath('/documents'))]);
  $('source-records').replaceChildren(el('p', `${sources.length} 次上传 · ${documents.length} 篇已索引文档 · ${runs.length} 次写入`));
  sources.forEach(source => $('source-records').append(details(`${source.name} · ${source.kind} · ${source.size} bytes`, source)));
  $('source-records').append(details('写入历史（含原始来源、解析选项和结果）', runs), details('统一 Document 与 raw_metadata', documents));
}
$('source-refresh').onclick = () => loadSources().catch(error => notice(error.message, true));

// Knowledge-base lifecycle: create, switch, clear derived state, and rebuild archives.
const knowledgeButton = el('button', '▦　知识库'); knowledgeButton.dataset.page = 'knowledge';
knowledgeButton.onclick = () => { showPage('knowledge'); loadKnowledgeBases().catch(error => notice(error.message, true)); };
document.querySelector('nav').append(knowledgeButton);
const knowledgePage = el('section', undefined, 'page'); knowledgePage.id = 'knowledge'; knowledgePage.hidden = true;
knowledgePage.innerHTML = `<div class="heading"><div><p class="eyebrow">KNOWLEDGE BASES</p><h1>隔离、检查与重建知识库</h1><p>每个知识库拥有独立的向量集合、关键词索引与来源目录。</p></div></div><div class="workspace"><article class="panel pad"><h2>新建知识库</h2><form id="kb-form"><label>名称<input id="kb-name" maxlength="100" required placeholder="例如：产品文档"></label><button class="primary">创建并切换</button></form></article><article class="panel pad"><h2>知识库列表</h2><p class="muted">清空只删除 Document 和检索索引；原始文件与写入历史保留，可随时重建。</p><div id="kb-list"></div></article></div>`;
document.querySelector('main').append(knowledgePage);

async function loadKnowledgeBases() {
  const items = await api('/v1/knowledge-bases');
  const select = $('knowledge-base'); select.replaceChildren(); $('kb-list').replaceChildren();
  items.forEach(item => {
    const option = el('option', item.name); option.value = item.id; option.selected = item.id === knowledgeBaseId; select.append(option);
    const card = el('div', undefined, 'item');
    card.append(el('strong', item.name), el('p', `${item.documents} 篇 Document · ${item.vector_chunks} 个向量 chunk · ${item.sources} 个原始来源 · ${item.runs} 条记录`, 'muted'));
    if (item.index?.status === 'blocked' || item.index?.status === 'unavailable') card.append(el('p', `索引不可用：${item.index.reason}`, 'error'));
    const use = el('button', item.id === knowledgeBaseId ? '当前使用' : '切换'); use.disabled = item.id === knowledgeBaseId; use.onclick = () => switchKnowledgeBase(item.id);
    const clear = el('button', '清空索引'); clear.onclick = async () => { if (!confirm(`确认清空“${item.name}”的 Document 与检索索引？原始文件和写入历史会保留。`)) return; clear.disabled = true; try { const result = await post(`/v1/knowledge-bases/${item.id}/clear`, {}); notice(`已清空：${result.deleted_documents} 篇 Document，原始来源仍保留。`); await loadKnowledgeBases(); if (item.id === knowledgeBaseId) await loadSources(); } catch(error) { notice(error.message, true); } finally { clear.disabled = false; } };
    const rebuild = el('button', '从原始数据重建'); rebuild.onclick = async () => { rebuild.disabled = true; notice('正在重建知识库…'); try { const result = await post(`/v1/knowledge-bases/${item.id}/rebuild`, {}); if (result.status !== 'complete') throw new Error(result.message || `重建失败：${result.error || result.status}。原始数据已保留，可重试。`); notice(`重建完成：执行 ${result.recipes} 个写入配置，恢复 ${result.documents} 篇 Document。`); await loadKnowledgeBases(); } catch(error) { notice(error.message, true); } finally { rebuild.disabled = false; } };
    card.append(use, clear, rebuild); $('kb-list').append(card);
  });
  if (!items.some(item => item.id === knowledgeBaseId)) switchKnowledgeBase('default');
}
function switchKnowledgeBase(id) {
  knowledgeBaseId = id; localStorage.setItem('knowledgeBaseId', id); history.length = 0; selectedSource = null;
  loadKnowledgeBases().catch(error => notice(error.message, true));
  notice('已切换知识库，后续写入、检索与回答均使用该库。');
}
$('knowledge-base').onchange = event => switchKnowledgeBase(event.target.value);
$('kb-form').onsubmit = event => formTask(event, async () => { const item = await post('/v1/knowledge-bases', {name:$('kb-name').value.trim()}); $('kb-name').value = ''; switchKnowledgeBase(item.id); });
loadKnowledgeBases().catch(error => notice(error.message, true));
