// voice/static/avatar/expressions.js
// Minimal v1 emotion set (neutral/focused/pleased) -> VRM expression-preset
// blendshape weights. Full tag set depends on a personality rewrite that
// hasn't happened yet (see spec's Non-goals) -- this stays intentionally
// small.

const ALL_KEYS = ['happy', 'relaxed', 'neutral'];

function zeroed() {
  return Object.fromEntries(ALL_KEYS.map((k) => [k, 0]));
}

function clamp01(x) {
  return Math.max(0, Math.min(1, x));
}

export function weightsForEmotion(tag, intensity) {
  const i = clamp01(intensity);
  const w = zeroed();
  if (tag === 'pleased') {
    w.happy = i;
  } else if (tag === 'focused') {
    w.neutral = i;
  }
  // 'neutral' and any unrecognized tag: all zero.
  return w;
}
