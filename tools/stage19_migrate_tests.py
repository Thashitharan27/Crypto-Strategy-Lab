"""Temporary Stage 19 helper for large test files that need small exact migrations."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "tests/test_gui_main_window.py",
    '''        values=window.values()\n        assert values["enable_strategy_profiles"] is True\n        assert values["di_execution_mode"] == "PREFERRED_SIDE_ONLY"\n''',
    '''        values=window.values()\n        assert "enable_strategy_profiles" not in values\n        assert "di_execution_mode" not in values\n        assert set(values["strategy_profiles"]) == {\n            "bull_long", "bull_short", "bear_long", "bear_short", "sideways_long", "sideways_short"\n        }\n''',
)

print("Applied Stage 19 current-contract test migrations.")
