from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            return text
        raise SystemExit(f"Stage 18 anchor not found: {label}")
    if count != 1:
        raise SystemExit(f"Stage 18 expected one anchor for {label}, found {count}")
    return text.replace(old, new, 1)


def replace_test_function(text: str, name: str, replacement: str) -> str:
    pattern = rf"(?ms)^def {re.escape(name)}\(.*?(?=^def |\Z)"
    matches = list(re.finditer(pattern, text))
    if not matches:
        if f"def {name}(" in replacement and replacement.strip() in text:
            return text
        raise SystemExit(f"Stage 18 test function not found: {name}")
    if len(matches) != 1:
        raise SystemExit(f"Stage 18 expected one test function {name}, found {len(matches)}")
    match = matches[0]
    return text[: match.start()] + replacement.rstrip() + "\n\n\n" + text[match.end() :]


# Fix the self-contradictory Git repository fixture test. The repo fixture deliberately
# initializes tmp_path, so use a child path that is actually not a repository.
p = ROOT / "tests" / "test_github_manager.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    'with pytest.raises(GitError, match="not a Git repository"): GitManager(tmp_path).validate()',
    'with pytest.raises(GitError, match="not a Git repository"): GitManager(tmp_path / "not-a-repo").validate()',
    "GitManager missing-repository assertion",
)
p.write_text(s, encoding="utf-8")


# Bring the main-window regressions in line with the Strategy-Profile-only GUI.
p = ROOT / "tests" / "test_gui_main_window.py"
s = p.read_text(encoding="utf-8")
if "import pandas as pd\n" not in s:
    s = replace_once(s, "import pytest\n", "import pandas as pd\nimport pytest\n", "module pandas import")

s = replace_once(
    s,
    '["Backtest Setup", "DI Direction & Pressure", "Support & Resistance", "Strategy Profiles", "Summary", "Portfolio", "Logs", "GitHub", "ChatGPT"]',
    '["Backtest Setup", "DI Direction & Pressure", "Support & Resistance", "Strategy Profiles", "Summary", "Portfolio", "GitHub", "ChatGPT"]',
    "market-ready tab expectation",
)

s = replace_test_function(
    s,
    "test_partial_stop_disables_ignored_core_stop_control",
    '''def test_profile_partial_stop_exposes_profile_stop_ladder_controls():
    app()
    window = MainWindow()
    try:
        controls = window.profile_editor.controls
        assert controls["stop_loss_multiple"].isEnabled()
        assert not controls["sl1_r"].isEnabled()
        assert not controls["sl1_close_pct"].isEnabled()
        assert not controls["sl2_r"].isEnabled()

        controls["partial_stop_enabled"].setChecked(True)
        assert controls["partial_stop_enabled"].isChecked()
        assert controls["sl1_r"].isEnabled()
        assert controls["sl1_close_pct"].isEnabled()
        assert controls["sl2_r"].isEnabled()
    finally:
        window.close()''',
)

s = replace_test_function(
    s,
    "test_partial_take_profit_disables_ignored_core_controls_and_calculates_remainder",
    '''def test_profile_partial_take_profit_uses_profile_ladder_controls():
    app()
    window = MainWindow()
    try:
        controls = window.profile_editor.controls
        assert controls["reward_risk_ratio"].isEnabled()
        assert not controls["tp1_r"].isEnabled()
        assert not controls["tp1_close_pct"].isEnabled()
        assert not controls["tp2_r"].isEnabled()

        controls["partial_profit_enabled"].setChecked(True)
        assert controls["partial_profit_enabled"].isChecked()
        assert not controls["reward_risk_ratio"].isEnabled()
        assert controls["tp1_r"].isEnabled()
        assert controls["tp1_close_pct"].isEnabled()
        assert controls["tp2_r"].isEnabled()
        assert controls["after_tp1_stop_mode"].isEnabled()
    finally:
        window.close()''',
)

s = replace_test_function(
    s,
    "test_partial_take_profit_and_partial_stop_loss_can_be_enabled_together",
    '''def test_profile_partial_profit_and_stop_can_be_enabled_together():
    app()
    window = MainWindow()
    try:
        controls = window.profile_editor.controls
        controls["partial_profit_enabled"].setChecked(True)
        controls["partial_stop_enabled"].setChecked(True)

        assert controls["partial_profit_enabled"].isChecked()
        assert controls["partial_stop_enabled"].isChecked()
        assert not controls["reward_risk_ratio"].isEnabled()
        assert controls["tp1_r"].isEnabled()
        assert controls["tp2_r"].isEnabled()
        assert controls["sl1_r"].isEnabled()
        assert controls["sl2_r"].isEnabled()
    finally:
        window.close()''',
)

p.write_text(s, encoding="utf-8")


# The hidden compatibility combo stores stable enum values. Present friendly text in
# the visible S/R summary instead of leaking those enum values to the user.
p = ROOT / "crypto_strategy_lab" / "gui" / "main_window.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '        mode = self.sr_filter_mode.currentText()\n        mode_line = f"Mode: {mode}"',
    '        mode_raw = self.sr_filter_mode.currentText()\n        mode = {\n            "ANALYSIS_ONLY": "Analysis Only",\n            "APPLY_ENTRY_RULES": "Apply Entry Rules",\n        }.get(mode_raw, mode_raw)\n        mode_line = f"Mode: {mode}"',
    "friendly S/R summary mode",
)
p.write_text(s, encoding="utf-8")

print("Stage 18 stale full-suite regressions repaired")
