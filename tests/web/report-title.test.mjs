import test from 'node:test';
import assert from 'node:assert/strict';
import {reportTitle} from '../../src/rag_framework/web/report-title.js';

test('custom report names are used without changing the report kind', () => {
  const report = {kind:'rag',name:'  云端重排对比  '};
  assert.equal(reportTitle(report), '云端重排对比');
  assert.equal(report.kind, 'rag');
});

test('legacy reports without a name keep the original kind-based title', () => {
  assert.equal(reportTitle({kind:'retrieval'}), 'RETRIEVAL 评估结果');
  assert.equal(reportTitle({kind:'rag',name:null}), 'RAG 评估结果');
});
