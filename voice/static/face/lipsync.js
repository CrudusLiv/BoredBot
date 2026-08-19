// voice/static/avatar/lipsync.js
// Replays a server-broadcast amplitude envelope (voice/tts.py's
// _broadcast_viseme) on a client-side timer, matched to elapsed time since
// the envelope's broadcast. No audio access needed -- TTS plays server-side
// via Windows MCI, the browser only ever sees these numbers.

export function startEnvelope(envelope, intervalMs, nowMs) {
  return { envelope, intervalMs, startMs: nowMs };
}

export function mouthWeightAt(state, nowMs) {
  const { envelope, intervalMs, startMs } = state;
  if (!envelope || envelope.length === 0) return 0;
  const elapsed = nowMs - startMs;
  const idx = Math.floor(elapsed / intervalMs);
  if (idx < 0 || idx >= envelope.length) return 0;
  return envelope[idx];
}
