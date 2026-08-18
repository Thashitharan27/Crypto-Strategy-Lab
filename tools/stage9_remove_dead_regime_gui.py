from pathlib import Path

# This migration is intentionally narrow: it removes only dead GUI remnants left
# after the earlier Strategy Profile reward/risk consolidation.
ROOT = Path(__file__).resolve().parents[1]
main = ROOT / "crypto_strategy_lab" / "gui" / "main_window.py"
text = main.read_text(encoding="utf-8")

old_block = '''        regime_targets_box=QGroupBox("Regime-Specific Reward/Risk"); regime_targets=QFormLayout(regime_targets_box)\n        regime_targets_help=QLabel("Bull uses the Bull Return Threshold below. Bear uses the separate bear threshold; returns between them are sideways. Warm-up trades use the base long/short ratios above.")\n        regime_targets_help.setWordWrap(True)\n        bull_long_conditional_help=QLabel("During bull regimes only: when BB width is at or above the minimum AND ADX is below the maximum, the conditional target replaces Long Bull Reward/Risk. Other bull longs keep the normal bull target.")\n        bull_long_conditional_help.setWordWrap(True)\n        form.addWidget(regime_targets_box)\n'''

if old_block not in text:
    raise RuntimeError("Stage 9 expected dead regime-target GUI block was not found")
text = text.replace(old_block, "", 1)

empty_updates = '        values.update({})\n        values.update({})\n'
if empty_updates not in text:
    raise RuntimeError("Stage 9 expected empty values.update remnants were not found")
text = text.replace(empty_updates, "", 1)

for stale in (
    'QGroupBox("Regime-Specific Reward/Risk")',
    'conditional target replaces Long Bull Reward/Risk',
    'regime_targets_help=',
    'bull_long_conditional_help=',
    'values.update({})',
):
    if stale in text:
        raise RuntimeError(f"Stage 9 stale GUI remnant remains: {stale}")

main.write_text(text, encoding="utf-8")

test = ROOT / "tests" / "test_stage9_dead_regime_gui_removed.py"
test.write_text('''from pathlib import Path\n\n\ndef test_dead_regime_reward_risk_gui_remnants_are_gone():\n    root = Path(__file__).resolve().parents[1]\n    text = (root / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")\n    for stale in (\n        'QGroupBox("Regime-Specific Reward/Risk")',\n        'conditional target replaces Long Bull Reward/Risk',\n        'regime_targets_help=',\n        'bull_long_conditional_help=',\n        'values.update({})',\n    ):\n        assert stale not in text\n\n\ndef test_di_tab_still_exposes_active_direction_and_pressure_controls():\n    root = Path(__file__).resolve().parents[1]\n    text = (root / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")\n    assert 'QGroupBox("Direction Selection")' in text\n    assert 'QGroupBox("DI Pressure Analysis")' in text\n    assert 'self.profile_editor.values()' in text\n''', encoding="utf-8")

print("Stage 9 dead regime GUI remnants removed")
