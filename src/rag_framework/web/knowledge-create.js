// Global defaults are resolved server-side; copying only uses the persisted binding.
export function newKnowledgeBasePayload(name, mode, binding) {
  const payload = {name: name.trim()};
  if (!payload.name) throw new Error('知识库名称不能为空');
  if (mode === 'global') return payload;
  if (mode !== 'copy') throw new Error('未知嵌入配置来源');
  if (!binding) throw new Error('当前知识库尚未绑定嵌入配置，不能复制；请选择全局默认配置。');
  return {...payload, embedding_binding: structuredClone(binding)};
}
