import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / ".claude" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
