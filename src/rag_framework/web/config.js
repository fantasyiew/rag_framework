// Draft validation is isolated; explicit application persists supported hot settings.
import {planConfigurationApplication, applyConfigurationApplication} from './config-apply.js?v=20261006-credentials';
export function initConfiguration({el, $, api, post, table, showPage, notice, getKnowledgeBaseId, reloadKnowledgeBases, askConfirmation}) {
const configNav = el('button', '⚙　配置工作台'); configNav.dataset.page = 'configuration';
document.querySelector('nav').append(configNav);
const configPage = el('section', undefined, 'page'); configPage.id = 'configuration'; configPage.hidden = true;
configPage.innerHTML = '<div class="heading"><div><h1>配置工作台</h1><p>编辑草稿、校验参数并检查变更。当前阶段草稿仅保存在本页面，离开或刷新后丢失。</p></div></div><article class="panel pad"><p id="config-status"></p><button id="config-reset" type="button">重新读取生效配置</button><button id="config-validate" type="button">校验草稿</button><div id="config-errors" role="status"></div></article><div id="config-fields"></div><article class="panel pad"><h2>变更对比</h2><div id="config-diff"></div></article>';
document.querySelector('main').append(configPage);
configPage.querySelector('.heading p').textContent = '编辑后点击“应用”，自动保存并生效；涉及当前知识库索引时会先确认重建。刷新会丢弃尚未应用的草稿。';
let configSchema, configCurrent, configDraft, globalPreset, configVersion = 0;
const embeddingName = name => name.startsWith('embedding_');
const activationText = (name, spec) => embeddingName(name) ? '应用时自动绑定，必要时确认重建；无需重启' : spec.activation === 'hot' ? '支持热更新' : spec.requires_rebuild_review ? '重启并检查索引兼容性' : '重启生效';
let applying = false;
function hasDraft() {
  return Boolean(configCurrent && JSON.stringify(configDraft) !== JSON.stringify(configCurrent));
}
const applyButton = el('button', '应用'); applyButton.type = 'button'; applyButton.className = 'primary'; applyButton.disabled = true;
$('config-validate').after(applyButton);
const configControls = new Map();
const credentialControls = new Map();
function renderCredentialStatus(result) {
  for (const [name, item] of credentialControls) {
    const state = result.credentials?.[name];
    item.status.textContent = !state ? '尚未校验' : state.configured ? (state.inherited_from ? `已配置（继承 ${state.inherited_from}）` : '已配置') : '未配置（禁用或匿名模式可不填）';
    item.status.className = state?.configured ? 'muted' : 'error';
  }
}
const configSections = new Map();
const defaultsButton = el('button', '恢复默认设置'); defaultsButton.type = 'button';
defaultsButton.disabled = true;
$('config-reset').after(defaultsButton);
defaultsButton.onclick = () => {
  if (!configSchema) return;
  configDraft.secret_refs = {};
  credentialControls.forEach(({control}, name) => { control.value = configCurrent.secret_refs?.[name] || configSchema.credentials[name].env; });
  for (const [name, control] of configControls) {
    const value = structuredClone(configSchema.fields[name].default ?? null);
    control.value = value === null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  }
  refreshConfigDraft();
  notice('草稿已恢复为项目内置默认配置，密钥引用已清空。当前生效配置保持不变，请检查差异并校验草稿。');
};
configNav.onclick = () => { showPage('configuration'); if (!configCurrent) loadConfig().catch(error => notice(error.message, true)); };
function configValue(spec, control) {
  if (control.dataset.nullable === 'true' && control.value === '') return null;
  const type = spec.type || spec.anyOf?.find(option => option.type !== 'null')?.type;
  if (type === 'boolean') return control.value === 'true';
  if (type === 'integer' || type === 'number') {
    if (control.value === '' || !Number.isFinite(Number(control.value))) throw new Error('请输入数值');
    return Number(control.value);
  }
  if (type === 'object' || type === 'array') return JSON.parse(control.value);
  return control.value;
}
function refreshConfigDraft() {
  $('config-errors').replaceChildren();
  const rows = []; let invalid = false;
  for (const [name, {control, status}] of credentialControls) {
    const value = control.value.trim();
    const original = configCurrent.secret_refs?.[name] || configSchema.credentials[name].env;
    if (value !== original) {
      configDraft.secret_refs[name] = value;
      rows.push([name + ' 环境变量引用', original, value, '知识库应用']);
      status.textContent = '引用已修改，请校验草稿';
    } else if (configCurrent.secret_refs?.[name]) configDraft.secret_refs[name] = original;
    else delete configDraft.secret_refs[name];
  }
  for (const [name, control] of configControls) {
    try {
      const value = configValue(configSchema.fields[name], control);
      configDraft.settings[name] = value;
      control.removeAttribute('aria-invalid');
      if (JSON.stringify(value) !== JSON.stringify(configCurrent.settings[name])) rows.push([
        name, JSON.stringify(configCurrent.settings[name]), JSON.stringify(value),
        activationText(name, configSchema.fields[name])]);
    } catch (error) {
      invalid = true; control.setAttribute('aria-invalid', 'true');
      $('config-errors').append(el('p', `${name}：${error.message}`, 'error'));
    }
  }
  $('config-diff').replaceChildren(rows.length ? table(['参数', '当前生效', '草稿', '生效方式'], rows) : el('p', '尚无变更'));
  for (const [sectionId, card] of configSections) {
    const field = configSchema.sections[sectionId].mode_field;
    const badge = card.querySelector('.config-mode-badge');
    if (badge) badge.textContent = '草稿模式：' + (configControls.get(field)?.value || '未设置');
  }
  return !invalid;
}
async function loadConfig() {
  const [schema, preset, snapshot, status, knowledgeBase] = await Promise.all([api('/v1/config/schema'), api('/v1/config/preset'), api('/v1/config/snapshot'), api('/v1/config/status'), api(`/v1/knowledge-bases/${encodeURIComponent(getKnowledgeBaseId())}`)]);
  globalPreset = structuredClone(preset);
  if (knowledgeBase.embedding_binding) {
    Object.assign(preset.settings, knowledgeBase.embedding_binding.settings);
    Object.assign(preset.secret_refs, knowledgeBase.embedding_binding.secret_refs);
  }
  configVersion = status.version;
  configSchema = schema; configCurrent = preset; configDraft = structuredClone(preset);
  configControls.clear(); configSections.clear(); $('config-fields').replaceChildren();
  credentialControls.clear();
  $('config-status').textContent = `当前知识库：${knowledgeBase.name} · ${knowledgeBase.embedding_binding ? '展示该库绑定的嵌入配置' : '嵌入配置待绑定，下方展示全局默认值'}。全局配置版本 ${configVersion}。点击“应用”保存并生效；当前库需要重建时会先确认，其他知识库的嵌入配置不变。标记需重启的参数暂不支持在线应用。`;
  $('config-status').className = knowledgeBase.embedding_binding ? '' : 'error';
  const groups = new Map();
  for (const [name, spec] of Object.entries(schema.fields)) {
    if (!groups.has(spec.group)) {
      const group = el('details', undefined, 'panel pad'); group.append(el('summary', spec.group));
      groups.set(spec.group, group); $('config-fields').append(group);
    }
    if (!configSections.has(spec.section)) {
      const section = schema.sections[spec.section];
      const card = el('fieldset', undefined, 'config-section'); card.dataset.tone = section.tone;
      const legend = el('legend', section.title);
      if (section.mode_field) legend.append(el('span', undefined, 'config-mode-badge'));
      const description = el('p', section.description, 'config-section-description');
      const fields = el('div', undefined, 'config-section-fields');
      card.append(legend, description, fields);
      groups.get(spec.group).append(card); configSections.set(spec.section, card);
    }
    const sectionFields = configSections.get(spec.section).querySelector('.config-section-fields');
    const variant = spec.anyOf?.find(option => option.type !== 'null') || spec;
    const choices = variant.enum || spec.enum || (variant.type === 'boolean' ? ['true', 'false'] : null);
    const control = el(choices ? 'select' : variant.type === 'object' || variant.type === 'array' || name.endsWith('_prompt') ? 'textarea' : 'input');
    if (name.endsWith('_prompt')) control.rows = 10;
    if (choices) choices.forEach(value => { const option = el('option', value); option.value = value; control.append(option); });
    const nullable = spec.anyOf?.some(option => option.type === 'null');
    if (nullable && choices) { const option = el('option', '未设置'); option.value = ''; control.prepend(option); }
    control.dataset.nullable = String(Boolean(nullable)); control.id = `config-${name}`;
    if (!choices && ['number', 'integer'].includes(variant.type)) {
      control.type = 'number'; control.step = variant.type === 'integer' ? '1' : 'any';
      if (variant.minimum !== undefined) control.min = variant.minimum;
      if (variant.maximum !== undefined) control.max = variant.maximum;
    }
    const value = preset.settings[name];
    control.value = value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    control.oninput = refreshConfigDraft;
    const label = el('label', name); label.htmlFor = control.id;
    if (name === 'default_top_k') label.textContent = 'top_k（检索硬上限）';
    const hint = el('span', undefined, 'config-hint');
    const icon = el('button', '?', 'config-help-icon'); icon.type = 'button';
    icon.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;min-width:16px;min-height:16px;padding:0;margin:0;border:1px solid #9baa9e;border-radius:50%;font:600 10px/1 sans-serif;background:transparent;color:#718175;box-sizing:border-box;flex:none;cursor:help';
    icon.setAttribute('aria-label', `${name} 参数详情`);
    const tooltip = el('span', undefined, 'config-tooltip');
    tooltip.hidden = true;
    tooltip.id = `config-help-${name}`; tooltip.setAttribute('role', 'tooltip');
    const range = [variant.minimum !== undefined ? `最小值：${variant.minimum}` : '',
      variant.exclusiveMinimum !== undefined ? `必须大于：${variant.exclusiveMinimum}` : '',
      variant.maximum !== undefined ? `最大值：${variant.maximum}` : '',
      choices ? `可选值：${choices.join('、')}` : ''].filter(Boolean).join('；');
    const defaultText = JSON.stringify(spec.default);
    tooltip.textContent = `${spec.description}\n${range}${nullable ? '\n支持留空（未设置）' : ''}\n默认值：${defaultText.length > 160 ? defaultText.slice(0, 160) + '…' : defaultText}\n${spec.env} · ${activationText(name, spec)}`;
    icon.setAttribute('aria-describedby', tooltip.id);
    control.setAttribute('aria-describedby', tooltip.id);
    const closeHint = () => { tooltip.hidden = true; };
    hint.onmouseenter = () => { tooltip.hidden = false; };
    hint.onmouseleave = closeHint;
    icon.onfocus = () => { tooltip.hidden = false; };
    icon.onblur = closeHint;
    icon.onkeydown = event => { if (event.key === 'Escape') closeHint(); };
    hint.append(icon, tooltip);
    const labelRow = el('div', undefined, 'config-label-row'); labelRow.append(label, hint);
    const help = el('p', `${spec.env} · ${nullable ? '留空为未设置 · ' : ''}${activationText(name, spec)}`, 'muted');
    const fieldBox = el('div', undefined, 'config-field');
    if (name.endsWith('_prompt')) fieldBox.classList.add('config-field-wide');
    fieldBox.append(labelRow, control, help); sectionFields.append(fieldBox); configControls.set(name, control);
    if (name === 'generation_user_prompt') fieldBox.append(el('p', '必须包含 {context}（编号证据）与 {question}；可选 {history}。字面花括号使用 {{ 和 }}。', 'muted'));
  }
  for (const [name, spec] of Object.entries(schema.credentials || {})) {
    const box = el('div', undefined, 'config-field');
    const control = el('input'); control.id = `config-${name}-reference`;
    control.value = preset.secret_refs?.[name] || spec.env;
    // Raw credentials must never be entered or returned by this workbench.
    control.readOnly = name !== 'embedding_api_key';
    const label = el('label', spec.label + '（环境变量名）'); label.htmlFor = control.id;
    const icon = el('span', '?', 'config-help-icon'); icon.title = '此处为服务端环境变量名称，不是 API Key 明文。状态会说明密钥是否存在或继承，校验不调用远程服务。';
    icon.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border:1px solid #9baa9e;border-radius:50%;font:600 10px/1 sans-serif;margin-left:6px;cursor:help';
    label.append(icon);
    const status = el('p', '尚未校验', 'muted');
    const help = el('p', name === 'embedding_api_key' ? '仅填写变量名，不是密钥本身。变量值在服务端环境或 .env 配置；引用随当前知识库保存。修改默认变量值后需重启。' : '只读引用。请在服务端环境或 .env 配置此变量的值后重启；此处不展示密钥明文。生成、评估及重排支持继承密钥。', 'muted');
    control.oninput = refreshConfigDraft;
    box.append(label, control, status, help);
    configSections.get(spec.section)?.querySelector('.config-section-fields').append(box);
    credentialControls.set(name, {control, status});
  }
  refreshConfigDraft();
  renderCredentialStatus(await post('/v1/config/draft/validate', configDraft));
  defaultsButton.disabled = false;
  applyButton.disabled = false;
}
applyButton.onclick = async () => {
  if (applying || !refreshConfigDraft()) return;
  applying = true;
  const knowledgeBaseId = getKnowledgeBaseId();
  applyButton.disabled = true;
  $('knowledge-base').disabled = true;
  defaultsButton.disabled = true; $('config-reset').disabled = true; $('config-validate').disabled = true;
  configControls.forEach(control => { control.disabled = true; });
  try {
    const validation = await post('/v1/config/draft/validate', configDraft);
    renderCredentialStatus(validation);
    if (!validation.valid) {
      $('config-errors').replaceChildren(...validation.errors.map(error => el('p', `${error.field}：${error.message}`, 'error')));
      return;
    }
    const knowledgeBase = await api(`/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`);
    const plan = planConfigurationApplication({draft: configDraft, current: configCurrent, globalPreset, schema: configSchema, knowledgeBase});
    const result = await applyConfigurationApplication({plan, knowledgeBaseId, expectedVersion: configVersion, post,
      confirmRebuild: () => askConfirmation({title: '应用并重建当前知识库', message: `“${knowledgeBase.name}”的嵌入配置或索引需要更新。应用将持久化配置，并替换当前库索引；原始数据和写入记录保留，其他库的嵌入配置与索引不变。全局参数对所有库生效。如需保留当前索引，请取消并前往知识库管理页新建知识库。是否继续？`, confirmLabel: '确认应用'}),
      onGlobalApplied: (updated, preset) => {
        configVersion = updated.version;
        globalPreset = structuredClone(preset);
        for (const [name, value] of Object.entries(preset.settings)) if (!embeddingName(name)) configCurrent.settings[name] = structuredClone(value);
      }});
    if (result.cancelled) return;
    if (result.validation) {
      $('config-errors').replaceChildren(...result.validation.errors.map(error => el('p', `${error.field}：${error.message}`, 'error')));
      return;
    }
    await loadConfig();
    await reloadKnowledgeBases();
    notice(result.rebuilt ? '已应用并持久化，当前知识库索引已重建，无需重启。' : result.bindingApplied || result.globalResult?.applied ? '已应用并持久化，无需重启。' : '配置没有变化。');
  } catch (error) {
    refreshConfigDraft();
    notice((error.globalApplied ? '全局参数已应用并持久化；' : '') + error.message + ' 未完成的草稿已保留。', true);
  } finally {
    applying = false; $('knowledge-base').disabled = false;
    applyButton.disabled = false; defaultsButton.disabled = false;
    $('config-reset').disabled = false; $('config-validate').disabled = false;
    configControls.forEach(control => { control.disabled = false; });
  }
};
$('config-reset').onclick = () => loadConfig().catch(error => notice(error.message, true));
$('config-validate').onclick = async () => {
  if (!refreshConfigDraft()) return;
  const button = $('config-validate'); button.disabled = true;
  try {
    const result = await post('/v1/config/draft/validate', configDraft);
    renderCredentialStatus(result);
    $('config-errors').replaceChildren();
    if (result.valid) $('config-errors').append(el('p', '参数及必要凭据校验通过（未验证网络连接或密钥有效性）。草稿尚未保存或生效。'));
    else result.errors.forEach(error => {
      $('config-errors').append(el('p', `${error.field}：${error.message}`, 'error'));
      configControls.get(error.field)?.setAttribute('aria-invalid', 'true');
      credentialControls.get(error.field)?.control.setAttribute('aria-invalid', 'true');
    });
    (result.warnings || []).forEach(warning => $('config-errors').append(el('p', warning, 'muted')));
  } catch (error) { notice(error.message, true); } finally { button.disabled = false; }
};
return {hasDraft, reload: loadConfig, isBusy: () => applying};
}
