// One entry point, with explicit partial-success reporting across two API operations.
const embeddingField = name => name.startsWith('embedding_');
const different = (left, right) => JSON.stringify(left) !== JSON.stringify(right);

export function planConfigurationApplication({draft, current, globalPreset, schema, knowledgeBase}) {
  const changed = Object.keys(draft.settings).filter(name => different(draft.settings[name], current.settings[name]));
  const blocked = changed.filter(name => !embeddingField(name) && schema.fields[name]?.activation !== 'hot');
  if (blocked.length) throw new Error('以下参数仍需要重启，尚不能通过“应用”保存：' + blocked.join('、') + '。请先恢复这些参数，其他草稿会保留。');
  const credentialChanged = (draft.secret_refs?.embedding_api_key || 'RAG_EMBEDDING_API_KEY') !== (current.secret_refs?.embedding_api_key || 'RAG_EMBEDDING_API_KEY');
  const binding = !knowledgeBase.embedding_binding || changed.some(embeddingField) || credentialChanged
    || knowledgeBase.index?.status === 'blocked';
  const rebuild = binding && (Boolean(knowledgeBase.index?.manifest)
    || knowledgeBase.index?.status === 'blocked' || knowledgeBase.index?.status === 'unavailable'
    || knowledgeBase.vector_chunks !== 0 || knowledgeBase.keyword_chunks !== 0);
  const preset = structuredClone(draft);
  for (const name of Object.keys(preset.settings)) if (embeddingField(name)) preset.settings[name] = globalPreset.settings[name];
  preset.secret_refs = structuredClone(globalPreset.secret_refs);
  return {binding, rebuild, preset,
    globalChanged: changed.some(name => !embeddingField(name)),
    profile: {schema_version: 1,
      settings: Object.fromEntries(Object.entries(draft.settings).filter(([name]) => embeddingField(name))),
      secret_refs: {embedding_api_key: draft.secret_refs?.embedding_api_key || 'RAG_EMBEDDING_API_KEY'}}};
}

export async function applyConfigurationApplication({plan, knowledgeBaseId, expectedVersion, post, confirmRebuild, onGlobalApplied}) {
  if (plan.rebuild && !await confirmRebuild()) return {cancelled: true};
  let globalResult;
  try {
    if (plan.globalChanged) {
      globalResult = await post('/v1/config/apply', {preset: plan.preset, expected_version: expectedVersion});
      if (!globalResult.valid) return {validation: globalResult};
      onGlobalApplied?.(globalResult, plan.preset);
    }
    if (plan.binding) {
      const result = await post(`/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/embedding-binding`,
        {profile: plan.profile, rebuild: plan.rebuild});
      if (result.rebuild && result.rebuild.status !== 'complete') throw new Error('知识库重建失败；原始数据保留，请检查模型配置后重试。');
      if (['blocked', 'unavailable'].includes(result.index?.status)) throw new Error('知识库配置已保存，但索引仍不可用，请检查模型或存储服务后重试。');
    }
    return {globalResult, bindingApplied: plan.binding, rebuilt: plan.rebuild};
  } catch (error) {
    error.globalApplied = Boolean(globalResult?.applied);
    throw error;
  }
}
