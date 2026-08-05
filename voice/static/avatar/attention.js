// voice/static/avatar/attention.js
// Client-side-only gaze: cursor position is trivially available in the
// browser via mousemove, so this never round-trips through the Python
// backend the way emotion/viseme do (see spec's Decisions table).

const YAW_MAX = 0.5;   // radians, ~28 degrees
const PITCH_MAX = 0.35; // radians, ~20 degrees

function clamp(x, lo, hi) {
  return Math.max(lo, Math.min(hi, x));
}

export function gazeAngles(cursorX, cursorY, viewportW, viewportH) {
  const nx = (cursorX / viewportW) * 2 - 1;   // -1..1
  const ny = (cursorY / viewportH) * 2 - 1;   // -1..1
  return {
    yaw: clamp(nx * YAW_MAX, -YAW_MAX, YAW_MAX),
    pitch: clamp(-ny * PITCH_MAX, -PITCH_MAX, PITCH_MAX),
  };
}
