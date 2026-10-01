import assert from 'node:assert/strict';
import test from 'node:test';
import {citationStatus} from '../src/rag_framework/web/citations.js';

const response = (text, citations, count) => ({answer: {text, citations}, retrieval: {
  final_context: [{chunk: {id: 'one'}}],
  steps: [{name: 'generate_answer', details: {context_count: count}}],
}});
test('valid citations are retained', () => {
  assert.equal(citationStatus(response('fact [1]', [{number: 1}], 1)).citations.length, 1);
});
test('retrieved evidence without inline citations has a distinct status', () => {
  assert.equal(citationStatus(response('fact', [], 1)).title, '该回答未提供引用');
});
test('zero generation context differs from unmarked evidence', () => {
  assert.equal(citationStatus(response('no evidence', [], 0)).title, '未检索到可用于生成的证据');
});
test('invalid citation markers are not treated as valid evidence', () => {
  assert.equal(citationStatus(response('fact [99]', [], 1)).title, '回答未提供有效引用');
});
