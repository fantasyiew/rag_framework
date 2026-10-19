// Consume a POST SSE response, including fragmented UTF-8 and CRLF boundaries.
export async function consumeEvaluation(response, onEvent) {
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : `评估请求失败 (${response.status})`);
  }
  if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('服务未返回进度流，请重启新版服务。');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', report = null;
  const dispatch = frame => {
    const lines = frame.split('\n').map(line => line.replace(/\r$/, ''));
    const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!event || !data) return;
    const value = JSON.parse(data);
    if (event === 'error') throw new Error(value.message || '评估执行失败');
    if (event === 'complete') report = value;
    onEvent(event, value);
  };
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        dispatch(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
      if (done) break;
    }
    if (!report) throw new Error('评估连接已中断，未收到最终报告；请检查实验报告后再重试。');
    return report;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
