"""Temporary Stage 19 helper: keep the GUI reset fixture from mutating its expected defaults."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "tests/test_gui_main_window.py"
text = path.read_text(encoding="utf-8")
old = '        changed["strategy_profiles"] = defaults["strategy_profiles"]\n'
new = '        changed["strategy_profiles"] = default_gui_config()["strategy_profiles"]\n'
if old in text:
    path.write_text(text.replace(old, new), encoding="utf-8")
print("GUI reset fixture uses an independent Strategy Profile defaults copy.")
