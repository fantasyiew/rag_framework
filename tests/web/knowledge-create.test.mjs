import assert from 'node:assert/strict';
import test from 'node:test';
import {newKnowledgeBasePayload} from '../../src/rag_framework/web/knowledge-create.js';

test('global default creation omits embedding override', () => {
  assert.deepEqual(newKnowledgeBasePayload(' new KB ', 'global', {settings:{embedding_dimensions:32}}), {name:'new KB'});
});

test('copy creation snapshots persisted embedding configuration including credential references', () => {
  const binding = {schema_version:1, settings:{embedding_mode:'compatible', embedding_model:'test-model', embedding_dimensions:32}, secret_refs:{embedding_api_key:'RAG_EMBEDDING_API_KEY'}};
  const payload = newKnowledgeBasePayload('copy', 'copy', binding);
  assert.deepEqual(payload.embedding_binding, binding);
  payload.embedding_binding.settings.embedding_dimensions = 64;
  assert.equal(binding.settings.embedding_dimensions, 32);
  assert.equal(payload.embedding_binding.secret_refs.embedding_api_key, 'RAG_EMBEDDING_API_KEY');
});

test('unbound source, unknown choice and blank name cannot create a KB', () => {
  assert.throws(() => newKnowledgeBasePayload('copy', 'copy', null), /尚未绑定/);
  assert.throws(() => newKnowledgeBasePayload('test', 'draft', {}), /未知/);
  assert.throws(() => newKnowledgeBasePayload(' ', 'global'), /名称/);
});
