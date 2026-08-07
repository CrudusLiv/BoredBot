# PyInstaller spec — builds the console=False Windows .exe for release.
# Build: pyinstaller voice.spec
#
# Gotchas (see CLAUDE.md / plan doc for the reasoning):
#  - upx=False: UPX corrupts CTranslate2 (faster-whisper) DLLs
#  - console=False: tray icon needs windowed mode; safety.py detects sys.frozen
#    and swaps input() for a tkinter dialog accordingly
#  - Model files (whisper/vosk/openwakeword) are NOT bundled — they download to
#    the user's cache on first run, keeping the installer small
#  - Kokoro (~800MB via torch) is NOT bundled — optional, installed separately
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_all

block_cipher = None

binaries = []
datas = [
    ("voice/static", "voice/static"),
    ("voice/config.json", "voice"),
]
hiddenimports = [
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "starlette.routing",
    "starlette.staticfiles",
]

for pkg in ("sounddevice", "onnxruntime", "ctranslate2"):
    binaries += collect_dynamic_libs(pkg)

for pkg in ("faster_whisper", "vosk", "openwakeword"):
    _datas, _binaries, _hidden = collect_all(pkg)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hidden

a = Analysis(
    ["voice/__main__.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["torch", "kokoro"],  # Kokoro TTS is optional — ships separately
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Vesper",
    console=False,
    upx=False,
    disable_windowed_traceback=False,
)
