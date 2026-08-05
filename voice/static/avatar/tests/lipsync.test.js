// voice/static/avatar/tests/lipsync.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { startEnvelope, mouthWeightAt } from '../lipsync.js';

test('mouthWeightAt returns the sample nearest elapsed time', () => {
  const state = startEnvelope([0.0, 0.5, 1.0, 0.5], 100, /* nowMs */ 1000);
  assert.equal(mouthWeightAt(state, 1000), 0.0);   // t=0 -> sample 0
  assert.equal(mouthWeightAt(state, 1150), 0.5);   // t=150ms -> sample 1 (floor(150/100)=1)
  assert.equal(mouthWeightAt(state, 1250), 1.0);   // t=250ms -> sample 2
});

test('mouthWeightAt returns 0 once past the envelope end', () => {
  const state = startEnvelope([0.0, 1.0], 100, 1000);
  assert.equal(mouthWeightAt(state, 1000 + 10_000), 0);
});

test('mouthWeightAt returns 0 for an empty envelope', () => {
  const state = startEnvelope([], 100, 1000);
  assert.equal(mouthWeightAt(state, 1000), 0);
});
