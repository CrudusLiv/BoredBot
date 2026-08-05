# tests/test_voice_tts_envelope.py
"""Tests for the synthetic lip-sync envelope generator in voice/tts.py.

No real audio decode -- duration comes from MCI at playback time (not
exercised here, that's a thin impure wrapper), and the envelope shape is
a pure function of (text, duration) so it's fully testable without audio."""
from __future__ import annotations

from voice.tts import _syllable_count, _estimate_envelope


def test_syllable_count_counts_vowel_groups():
    assert _syllable_count("hello there") == 4   # hel-lo (e,o) + the-re (e,e) per the vowel-group regex
    assert _syllable_count("a") == 1
    assert _syllable_count("") == 1               # never zero -- avoids div-by-zero downstream


def test_syllable_count_floors_each_word_at_one():
    assert _syllable_count("rhythm") == 1          # no vowel-letter group, still counts as 1


def test_estimate_envelope_empty_duration_returns_empty():
    assert _estimate_envelope("hello", 0.0) == []
    assert _estimate_envelope("hello", -1.0) == []


def test_estimate_envelope_sample_count_matches_duration_and_hz():
    env = _estimate_envelope("hello there friend", 2.0, hz=10.0)
    assert len(env) == 20


def test_estimate_envelope_values_stay_in_unit_range():
    env = _estimate_envelope("a fairly long sentence to synthesize", 3.0, hz=25.0)
    assert all(0.0 <= v <= 1.0 for v in env)


def test_estimate_envelope_is_deterministic():
    a = _estimate_envelope("same text every time", 1.5, hz=25.0)
    b = _estimate_envelope("same text every time", 1.5, hz=25.0)
    assert a == b
