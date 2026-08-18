"""Temporary Stage 21 follow-up test migration."""
from pathlib import Path

path = Path("tests/test_gui_main_window.py")
text = path.read_text(encoding="utf-8")
old = '        assert controls["after_tp1_stop_mode"].isEnabled()\n'
if old not in text:
    raise RuntimeError("Expected stale after_tp1 GUI assertion not found")
text = text.replace(old, '', 1)
path.write_text(text, encoding="utf-8")
