// voice/static/avatar/tests/attention.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gazeAngles } from '../attention.js';

test('cursor at viewport center returns near-zero angles', () => {
  const { yaw, pitch } = gazeAngles(500, 400, 1000, 800);
  assert.ok(Math.abs(yaw) < 0.01);
  assert.ok(Math.abs(pitch) < 0.01);
});

test('cursor at the far right yields a positive yaw, clamped', () => {
  const { yaw } = gazeAngles(1000, 400, 1000, 800);
  assert.ok(yaw > 0);
  assert.ok(yaw <= 0.5);   // clamp ceiling, see implementation
});

test('cursor at the far left yields a negative yaw, clamped', () => {
  const { yaw } = gazeAngles(0, 400, 1000, 800);
  assert.ok(yaw < 0);
  assert.ok(yaw >= -0.5);
});

test('cursor above/below center yields opposite-sign pitch, clamped', () => {
  const top = gazeAngles(500, 0, 1000, 800);
  const bottom = gazeAngles(500, 800, 1000, 800);
  assert.ok(top.pitch > 0);
  assert.ok(bottom.pitch < 0);
  assert.ok(Math.abs(top.pitch) <= 0.35);
});
