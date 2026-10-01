// Phase 1: an in-memory draft; validation never changes the running service.
export function initConfiguration({el, $, api, post, table, showPage, notice}) {
const configNav = el('button', '⚙　配置工作台'); configNav.dataset.page = 'configuration';
document.querySelector('nav').append(configNav);
const configPage = el('section', undefined, 'page'); configPage.id = 'configuration'; configPage.hidden = true;
configPage.innerHTML = '<div class="heading"><div><h1>配置工作台</h1><p>编辑草稿、校验参数并检查变更。当前阶段草稿仅保存在本页面，离开或刷新后丢失。</p></div></div><article class="panel pad"><p id="config-status"></p><button id="config-reset" type="button">重新读取生效配置</button><button id="config-validate" type="button">校验草稿</button><div id="config-errors" role="status"></div></article><div id="config-fields"></div><article class="panel pad"><h2>变更对比</h2><div id="config-diff"></div></article>';
document.querySelector('main').append(configPage);
let configSchema, configCurrent, configDraft;
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
        configSchema.fields[name].requires_rebuild_review ? '重启；检查索引兼容性，可能需重建' : '重启生效']);
    } catch (error) {
      invalid = true; control.setAttribute('aria-invalid', 'true');
      $('config-errors').append(el('p', `${name}：${error.message}`, 'error'));
    }
  }
  $('config-diff').replaceChildren(rows.length ? table(['参数', '当前生效', '草稿', '生效方式'], rows) : el('p', '尚无变更'));
  return !invalid;
}
async function loadConfig() {
  const [schema, preset, snapshot] = await Promise.all([api('/v1/config/schema'), api('/v1/config/preset'), api('/v1/config/snapshot')]);
  configSchema = schema; configCurrent = preset; configDraft = structuredClone(preset);
  configControls.clear(); $('config-fields').replaceChildren();
  $('config-status').textContent = `当前生效配置：${snapshot.config_hash}。草稿校验通过也不会自动生效。密钥通过环境变量配置。`;
  const groups = new Map();
  for (const [name, spec] of Object.entries(schema.fields)) {
    if (!groups.has(spec.group)) {
      const group = el('details', undefined, 'panel pad'); group.append(el('summary', spec.group));
      groups.set(spec.group, group); $('config-fields').append(group);
    }
    const variant = spec.anyOf?.find(option => option.type !== 'null') || spec;
    const choices = variant.enum || spec.enum || (variant.type === 'boolean' ? ['true', 'false'] : null);
    const control = el(choices ? 'select' : variant.type === 'object' || variant.type === 'array' ? 'textarea' : 'input');
    if (choices) choices.forEach(value => { const option = el('option', value); option.value = value; control.append(option); });
    const nullable = spec.anyOf?.some(option => option.type === 'null');
    if (nullable && choices) { const option = el('option', '未设置'); option.value = ''; control.prepend(option); }
    control.dataset.nullable = String(Boolean(nullable)); control.id = `config-${name}`;
    if (!choices && ['number', 'integer'].includes(variant.type)) {
      control.type = 'number'; control.step = variant.type === 'integer' ? '1' : 'any';
      if (spec.minimum !== undefined) control.min = spec.minimum;
      if (spec.maximum !== undefined) control.max = spec.maximum;
    }
    const value = preset.settings[name];
    control.value = value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    control.oninput = refreshConfigDraft;
    const label = el('label', name); label.htmlFor = control.id;
    const help = el('p', `${spec.env} · ${nullable ? '留空为未设置 · ' : ''}${spec.requires_rebuild_review ? '修改后检查索引兼容性' : '重启生效'}`, 'muted');
    groups.get(spec.group).append(label, control, help); configControls.set(name, control);
  }
  refreshConfigDraft();
  defaultsButton.disabled = false;
}
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
