import test from 'node:test';
import assert from 'node:assert/strict';
import {consumeEvaluation} from '../../src/rag_framework/web/evaluation-progress.js';

function stream(text, size=3) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({start(controller) {
    for (let i=0; i<bytes.length; i+=size) controller.enqueue(bytes.slice(i,i+size));
    controller.close();
  }}), {headers:{'Content-Type':'text/event-stream'}});
}

test('fragmented UTF-8, CRLF, heartbeat and completion are parsed', async () => {
  const events = [];
  const response = stream(': heartbeat\r\n\r\nevent: start\r\ndata: {"total":70,"completed":0}\r\n\r\nevent: progress\ndata: {"completed":1,"case_id":"用例一"}\n\nevent: complete\ndata: {"id":"report","case_count":70}\n\n');
  const report = await consumeEvaluation(response, (event,value)=>events.push([event,value]));
  assert.equal(report.id, 'report');
  assert.deepEqual(events.map(([event])=>event), ['start','progress','complete']);
  assert.equal(events[1][1].case_id, '用例一');
});

test('terminal error and missing final report do not appear successful', async () => {
  await assert.rejects(consumeEvaluation(stream('event: error\ndata: {"message":"保存失败"}\n\n'), ()=>{}), /保存失败/);
  await assert.rejects(consumeEvaluation(stream('event: progress\ndata: {"completed":1}\n\n'), ()=>{}), /中断/);
});

test('HTTP failures retain actionable preflight message', async () => {
  await assert.rejects(consumeEvaluation(new Response('{"detail":"测试集不存在"}',{status:404}), ()=>{}), /测试集不存在/);
});
