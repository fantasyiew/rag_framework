import test from 'node:test';
import assert from 'node:assert/strict';
import {snapshotRows} from '../../src/rag_framework/web/report-snapshot.js';

test('report uses stored run parameters and bound KB embeddings', () => {
  const report = {kind:'rag', k:5, config_snapshot:{snapshot_id:'saved-id', config_version:2,
    settings:{query_planner_mode:'disabled',default_top_k:8,embedding_model:'global-model',embedding_dimensions:16},
    embedding_binding:{settings:{embedding_mode:'hash',embedding_model:'bound-model',embedding_dimensions:32}},
    evaluation:{kind:'retrieval',k:3}}};
  const rows = new Map(snapshotRows(report));
  assert.equal(rows.get('快照 ID'), 'saved-id');
  assert.equal(rows.get('评估类型 / K'), 'retrieval / 3');
  assert.equal(rows.get('嵌入模式 / 模型 / 维度'), 'hash / bound-model / 32');
  assert.equal(rows.get('检索 top_k 硬上限'), '8');
});

test('missing snapshot is not replaced by current configuration', () => {
  assert.equal(snapshotRows({kind:'rag',k:5}), null);
  const rows = new Map(snapshotRows({kind:'retrieval',k:5,config_snapshot:{settings:{}}}));
  assert.match(rows.get('快照 ID'), /旧版/);
  assert.equal(rows.get('评估类型 / K'), 'retrieval / 5');
});
