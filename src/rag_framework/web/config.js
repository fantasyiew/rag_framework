// Draft validation is isolated; explicit application persists supported hot settings.
export function initConfiguration({el, $, api, post, table, showPage, notice}) {
const configNav = el('button', '⚙　配置工作台'); configNav.dataset.page = 'configuration';
document.querySelector('nav').append(configNav);
const configPage = el('section', undefined, 'page'); configPage.id = 'configuration'; configPage.hidden = true;
configPage.innerHTML = '<div class="heading"><div><h1>配置工作台</h1><p>编辑草稿、校验参数并检查变更。当前阶段草稿仅保存在本页面，离开或刷新后丢失。</p></div></div><article class="panel pad"><p id="config-status"></p><button id="config-reset" type="button">重新读取生效配置</button><button id="config-validate" type="button">校验草稿</button><div id="config-errors" role="status"></div></article><div id="config-fields"></div><article class="panel pad"><h2>变更对比</h2><div id="config-diff"></div></article>';
document.querySelector('main').append(configPage);
configPage.querySelector('.heading p').textContent = '编辑草稿并校验。可热更新参数可应用并持久化；刷新会丢弃尚未应用的草稿。';
let configSchema, configCurrent, configDraft, configVersion = 0;
const applyButton = el('button', '应用并持久化'); applyButton.type = 'button'; applyButton.disabled = true;
$('config-validate').after(applyButton);
const configControls = new Map();
const defaultsButton = el('button', '恢复默认设置'); defaultsButton.type = 'button';
defaultsButton.disabled = true;
$('config-reset').after(defaultsButton);
defaultsButton.onclick = () => {
  if (!configSchema) return;
  configDraft.secret_refs = {};
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
  for (const [name, control] of configControls) {
    try {
      const value = configValue(configSchema.fields[name], control);
      configDraft.settings[name] = value;
      control.removeAttribute('aria-invalid');
      if (JSON.stringify(value) !== JSON.stringify(configCurrent.settings[name])) rows.push([
        name, JSON.stringify(configCurrent.settings[name]), JSON.stringify(value),
        configSchema.fields[name].activation === 'hot' ? '可热更新' : configSchema.fields[name].requires_rebuild_review ? '重启；检查索引兼容性，可能需重建' : '重启生效']);
    } catch (error) {
      invalid = true; control.setAttribute('aria-invalid', 'true');
      $('config-errors').append(el('p', `${name}：${error.message}`, 'error'));
    }
  }
  $('config-diff').replaceChildren(rows.length ? table(['参数', '当前生效', '草稿', '生效方式'], rows) : el('p', '尚无变更'));
  return !invalid;
}
async function loadConfig() {
  const [schema, preset, snapshot, status] = await Promise.all([api('/v1/config/schema'), api('/v1/config/preset'), api('/v1/config/snapshot'), api('/v1/config/status')]);
  configVersion = status.version;
  configSchema = schema; configCurrent = preset; configDraft = structuredClone(preset);
  configControls.clear(); $('config-fields').replaceChildren();
  $('config-status').textContent = `当前生效配置：${snapshot.config_hash} · 版本 ${configVersion}。点击“应用并持久化”使可热更新参数生效；其他参数需要重启。`;
  const groups = new Map();
  for (const [name, spec] of Object.entries(schema.fields)) {
    if (!groups.has(spec.group)) {
      const group = el('details', undefined, 'panel pad'); group.append(el('summary', spec.group));
      groups.set(spec.group, group); $('config-fields').append(group);
    }
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
    tooltip.textContent = `${spec.description}\n${range}${nullable ? '\n支持留空（未设置）' : ''}\n默认值：${defaultText.length > 160 ? defaultText.slice(0, 160) + '…' : defaultText}\n${spec.env} · ${spec.activation === 'hot' ? '应用后热更新并持久化' : spec.requires_rebuild_review ? '需重启并检查索引兼容性' : '需重启服务'}`;
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
    const help = el('p', `${spec.env} · ${nullable ? '留空为未设置 · ' : ''}${spec.activation === 'hot' ? '支持热更新' : spec.requires_rebuild_review ? '重启并检查索引兼容性' : '重启生效'}`, 'muted');
    groups.get(spec.group).append(labelRow, control, help); configControls.set(name, control);
    if (name === 'generation_user_prompt') groups.get(spec.group).append(el('p', '必须包含 {context}（编号证据）与 {question}；可选 {history}。字面花括号使用 {{ 和 }}。', 'muted'));
  }
  refreshConfigDraft();
  defaultsButton.disabled = false;
  applyButton.disabled = false;
}
applyButton.onclick = async () => {
  if (!refreshConfigDraft()) return;
  applyButton.disabled = true;
  defaultsButton.disabled = true; $('config-reset').disabled = true; $('config-validate').disabled = true;
  configControls.forEach(control => { control.disabled = true; });
  try {
    const result = await post('/v1/config/apply', {preset: configDraft, expected_version: configVersion});
    if (!result.valid) {
      $('config-errors').replaceChildren(...result.errors.map(error => el('p', `${error.field}：${error.message}`, 'error')));
      return;
    }
    await loadConfig();
    notice(result.applied ? `配置版本 ${result.version} 已生效并持久化，重启后保留。` : '配置没有变化。');
  } catch (error) { notice(error.message, true); } finally {
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
    $('config-errors').replaceChildren();
    if (result.valid) $('config-errors').append(el('p', '校验通过。草稿尚未保存或生效。'));
    else result.errors.forEach(error => {
      $('config-errors').append(el('p', `${error.field}：${error.message}`, 'error'));
      configControls.get(error.field)?.setAttribute('aria-invalid', 'true');
    });
  } catch (error) { notice(error.message, true); } finally { button.disabled = false; }
};
}
