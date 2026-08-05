// voice/static/avatar/tests/expressions.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { weightsForEmotion } from '../expressions.js';

test('neutral returns all-zero weights', () => {
  const w = weightsForEmotion('neutral', 0.5);
  assert.equal(w.happy, 0);
  assert.equal(w.relaxed, 0);
});

test('focused scales the "relaxed" preset down and adds a slight neutral lean', () => {
  const w = weightsForEmotion('focused', 1.0);
  assert.ok(w.relaxed === 0);
  assert.ok(w.neutral > 0);
});

test('pleased scales the "happy" preset by intensity', () => {
  const half = weightsForEmotion('pleased', 0.5);
  const full = weightsForEmotion('pleased', 1.0);
  assert.equal(half.happy, 0.5);
  assert.equal(full.happy, 1.0);
});

test('unknown tag falls back to neutral (all zero)', () => {
  const w = weightsForEmotion('bogus', 1.0);
  assert.equal(w.happy, 0);
});

test('intensity is clamped to [0, 1]', () => {
  assert.equal(weightsForEmotion('pleased', 5).happy, 1.0);
  assert.equal(weightsForEmotion('pleased', -5).happy, 0.0);
});
