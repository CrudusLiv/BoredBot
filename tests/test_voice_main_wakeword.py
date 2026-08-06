from pathlib import Path

from voice.main import _resolve_wakeword_model_path


def test_resolve_wakeword_model_path_returns_configured_value_when_set():
    assert _resolve_wakeword_model_path("C:/custom/model.onnx") == "C:/custom/model.onnx"


def test_resolve_wakeword_model_path_falls_back_to_bundled_default_when_empty():
    result = _resolve_wakeword_model_path("")
    assert result.endswith(str(Path("voice") / "models" / "vesper.onnx"))


def test_resolve_wakeword_model_path_falls_back_when_whitespace_only():
    result = _resolve_wakeword_model_path("   ")
    assert result.endswith(str(Path("voice") / "models" / "vesper.onnx"))
