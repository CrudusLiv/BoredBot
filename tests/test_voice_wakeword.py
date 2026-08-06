from voice.wakeword import _MuteCooldown


def test_mute_cooldown_not_deaf_before_any_mute():
    cooldown = _MuteCooldown(cooldown_s=1.5)
    assert cooldown.is_deaf(0.0) is False


def test_mute_cooldown_deaf_immediately_after_mute():
    cooldown = _MuteCooldown(cooldown_s=1.5)
    cooldown.note_muted(now=10.0)
    assert cooldown.is_deaf(10.5) is True


def test_mute_cooldown_expires_after_unmute():
    cooldown = _MuteCooldown(cooldown_s=1.5)
    cooldown.note_muted(now=10.0)
    assert cooldown.is_deaf(11.6) is False


def test_mute_cooldown_deadline_slides_while_still_muted():
    cooldown = _MuteCooldown(cooldown_s=1.5)
    cooldown.note_muted(now=10.0)
    cooldown.note_muted(now=10.4)  # still muted — deadline slides forward
    assert cooldown.is_deaf(11.4) is True   # would've expired from the first note_muted alone
    assert cooldown.is_deaf(11.95) is False
