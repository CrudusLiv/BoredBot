// voice/static/avatar/tests/idle.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { breathingScale, shouldBlink, nextBlinkDelay } from '../idle.js';

test('breathingScale oscillates around 1.0 within a tight band', () => {
  const samples = [0, 500, 1000, 1500, 2000].map(breathingScale);
  for (const s of samples) {
    assert.ok(s >= 0.97 && s <= 1.03, `expected ~1.0, got ${s}`);
  }
  // not constant -- it must actually move over a full cycle
  assert.notEqual(samples[0], samples[2]);
});

test('shouldBlink is false before the scheduled delay has elapsed', () => {
  assert.equal(shouldBlink(1000, 0, 3000), false);
});

test('shouldBlink is true once elapsed time reaches the delay', () => {
  assert.equal(shouldBlink(3000, 0, 3000), true);
  assert.equal(shouldBlink(4000, 0, 3000), true);
});

test('nextBlinkDelay stays within the documented 2500-6000ms range', () => {
  const rand = () => 0;
  assert.equal(nextBlinkDelay(rand), 2500);
  const randMax = () => 0.999999;
  assert.ok(nextBlinkDelay(randMax) < 6000);
  assert.ok(nextBlinkDelay(randMax) >= 2500);
});
