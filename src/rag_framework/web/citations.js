export function citationStatus(response) {
  const citations = response.answer.citations || [];
  const step = [...(response.retrieval.steps || [])].reverse().find(item => item.name === 'generate_answer');
  const count = step?.details?.context_count ?? response.retrieval.final_context.length;
  if (citations.length) return {title: `引用证据 · ${citations.length} 条`, citations};
  if (!count) return {title: '未检索到可用于生成的证据', message: '本次回答没有可用检索上下文，因此没有引用证据。'};
  const marked = /\[\d+\]/.test(response.answer.text);
  return {title: marked ? '回答未提供有效引用' : '该回答未提供引用',
    message: marked ? '回答中的引用编号未匹配实际生成上下文。检索证据仍可在右侧查看。'
                    : '已检索到证据，但回答未标注引用。可在右侧查看上下文；这不表示证据未被使用。'};
}
