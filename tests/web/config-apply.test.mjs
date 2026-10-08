import assert from 'node:assert/strict';
import test from 'node:test';
import {planConfigurationApplication, applyConfigurationApplication} from '../../src/rag_framework/web/config-apply.js';

const preset = () => ({schema_version: 1, settings: {embedding_mode:'hash', embedding_dimensions:16, default_top_k:6, chunk_size:800}, secret_refs:{}});
function input(changes = {}, baseChanges = {}) {
  const current = preset();
  const draft = structuredClone(current); Object.assign(draft.settings, changes);
  return {draft, current, globalPreset:preset(),
    schema:{fields:{default_top_k:{activation:'hot'}, chunk_size:{activation:'restart'}}},
    knowledgeBase:{embedding_binding:{settings:{embedding_dimensions:16}}, index:{status:'empty'}, vector_chunks:0, keyword_chunks:0, ...baseChanges}};
}

test('hot-only changes never bind or rebuild, and bound embedding cannot override global default', async () => {
  const options = input({default_top_k:3});
  options.current.settings.embedding_dimensions = options.draft.settings.embedding_dimensions = 32;
  const plan = planConfigurationApplication(options);
  assert.equal(plan.binding, false);
  assert.equal(plan.preset.settings.embedding_dimensions, 16);
  const calls = [];
  const result = await applyConfigurationApplication({plan, knowledgeBaseId:'one', expectedVersion:2,
    post:async (path, body) => {calls.push({path, body}); return {valid:true, applied:true, version:3};}});
  assert.equal(calls.length, 1); assert.equal(calls[0].body.expected_version, 2);
  assert.equal(result.bindingApplied, false);
});

test('empty KB embedding edits bind without clearing or rebuilding', async () => {
  const plan = planConfigurationApplication(input({embedding_dimensions:32}));
  assert.equal(plan.rebuild, false);
  const calls = [];
  await applyConfigurationApplication({plan, knowledgeBaseId:'empty', post:async (path, body) => {calls.push({path, body}); return {index:{status:'empty'}};}});
  assert.equal(calls.length, 1); assert.equal(calls[0].body.rebuild, false);
  assert.equal(calls[0].body.profile.settings.embedding_dimensions, 32);
});

test('existing index including cleared manifest requires confirmation; cancel writes nothing', async () => {
  const plan = planConfigurationApplication(input({embedding_dimensions:32}, {index:{status:'ready', manifest:{}}}));
  assert.equal(plan.rebuild, true);
  let writes = 0;
  const result = await applyConfigurationApplication({plan, confirmRebuild:async () => false, post:async () => {writes++;}});
  assert.equal(result.cancelled, true); assert.equal(writes, 0);
});

test('mixed edits apply global settings and embedding through one orchestration', async () => {
  const plan = planConfigurationApplication(input({embedding_dimensions:32, default_top_k:3}, {vector_chunks:5}));
  const paths = []; let applied = false;
  const result = await applyConfigurationApplication({plan, knowledgeBaseId:'test', expectedVersion:1, confirmRebuild:async () => true,
    onGlobalApplied:() => {applied = true;}, post:async path => {
      paths.push(path); return path === '/v1/config/apply' ? {valid:true, applied:true, version:2} : {index:{status:'ready'}, rebuild:{status:'complete'}};
    }});
  assert.equal(applied, true); assert.equal(result.rebuilt, true);
  assert.deepEqual(paths, ['/v1/config/apply', '/v1/knowledge-bases/test/embedding-binding']);
});

test('restart-only edits fail before any operation', () => {
  assert.throws(() => planConfigurationApplication(input({chunk_size:900, embedding_dimensions:32})), /chunk_size/);
});

test('global validation or version failure prevents embedding mutation', async () => {
  const plan = planConfigurationApplication(input({default_top_k:3, embedding_dimensions:32}));
  let calls = 0;
  const result = await applyConfigurationApplication({plan, post:async () => {calls++; return {valid:false, errors:[]};}});
  assert.equal(calls, 1); assert.equal(result.validation.valid, false);
  await assert.rejects(applyConfigurationApplication({plan, post:async () => {throw new Error('version conflict');}}), /version conflict/);
});

test('rebuild failure reports successful global persistence, instead of claiming rollback', async () => {
  const plan = planConfigurationApplication(input({default_top_k:3, embedding_dimensions:32}, {vector_chunks:1}));
  let baselineUpdated = false;
  await assert.rejects(applyConfigurationApplication({plan, knowledgeBaseId:'test', confirmRebuild:async () => true,
    onGlobalApplied:() => {baselineUpdated = true;}, post:async path => path === '/v1/config/apply'
      ? {valid:true, applied:true, version:2} : {rebuild:{status:'failed'}}}), error => {
    assert.equal(error.globalApplied, true); assert.match(error.message, /重建失败/); return true;
  });
  assert.equal(baselineUpdated, true);
});

test('pending binding or blocked index can be recovered with unchanged draft', () => {
  assert.equal(planConfigurationApplication(input({}, {embedding_binding:null})).binding, true);
  assert.equal(planConfigurationApplication(input({}, {index:{status:'blocked'}})).rebuild, true);
});
