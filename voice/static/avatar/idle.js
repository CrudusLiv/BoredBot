// voice/static/avatar/idle.js
// Pure timing/motion functions for the avatar's idle animation. No Three.js,
// no DOM -- scene.js calls these every frame and applies the results to the
// loaded VRM's bone/blendshape state.

const BREATH_PERIOD_MS = 4000;
const BREATH_AMPLITUDE = 0.02;

export function breathingScale(elapsedMs) {
  const phase = (elapsedMs / BREATH_PERIOD_MS) * Math.PI * 2;
  return 1.0 + Math.sin(phase) * BREATH_AMPLITUDE;
}

export function shouldBlink(elapsedMs, lastBlinkMs, nextBlinkDelayMs) {
  return elapsedMs - lastBlinkMs >= nextBlinkDelayMs;
}

const BLINK_MIN_MS = 2500;
const BLINK_MAX_MS = 6000;

export function nextBlinkDelay(rand = Math.random) {
  return BLINK_MIN_MS + rand() * (BLINK_MAX_MS - BLINK_MIN_MS);
}
