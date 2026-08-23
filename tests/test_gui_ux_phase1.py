"""Safety and presentation-boundary tests for GUI UX Phase 1."""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from crypto_strategy_lab.data_lake_config import ReportingConfig, ResearchRunConfig
from crypto_strategy_lab.gui.ux_presentation import (ENUM_LABELS, PROFILE_LABELS,
    REPORT_PRESETS, apply_report_preset, clone_profile_pair, display_percentage,
    parse_percentage)

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "crypto_strategy_lab/gui/v2_main_window.py"


@pytest.mark.parametrize(("native", "shown"), ((.01,"1.00%"),(.0002,"0.02%"),(.0005,"0.05%"),(.002,"0.20%")))
def test_percentage_display_and_edit_roundtrip(native, shown):
    assert display_percentage(native) == shown
    assert parse_percentage(shown) == native


def test_friendly_enum_labels_preserve_native_values():
    assert ENUM_LABELS["strategy_profile_run_mode"]["COMBINED_SHARED_CAPITAL"] == "Combined — Shared Account"
    assert ENUM_LABELS["tie_policy"]["PESSIMISTIC"] == "Conservative — Stop First"
    assert set(PROFILE_LABELS) == {"bull_long","bull_short","bear_long","bear_short","sideways_long","sideways_short"}


def test_report_preset_mapping_is_explicit_and_deterministic():
    base = ReportingConfig(run_name="keep-me", output_dir="keep/this")
    for preset in REPORT_PRESETS:
        first = apply_report_preset(base, preset)
        second = apply_report_preset(base, preset)
        assert first == second and first.run_name == "keep-me" and first.output_dir == "keep/this"
    assert apply_report_preset(base,"QUICK").create_standard_charts is False
    assert apply_report_preset(base,"STANDARD").create_standard_charts is True
    assert apply_report_preset(base,"DEEP_RESEARCH").enable_trade_telemetry is True


def test_copy_profile_pair_does_not_alias_rule_payloads():
    config=ResearchRunConfig(); strategy=config.strategy.profiles["bull_long"]
    strategy=replace(strategy,entry_rules=({"indicator":"ADX","advanced":{"future":1}},))
    copied_strategy,copied_execution=clone_profile_pair(strategy,config.execution.profiles["bull_long"])
    copied_strategy.entry_rules[0]["advanced"]["future"]=2
    assert strategy.entry_rules[0]["advanced"]["future"] == 1
    assert copied_execution == config.execution.profiles["bull_long"]


def test_active_gui_has_workflow_and_no_unsafe_or_parallel_execution_path():
    source=GUI.read_text(encoding="utf-8")
    for page in ("Setup","Strategy & Profiles","Research Features","Risk & Execution","Reports & Diagnostics","Review & Run","Results Dashboard","Data Library","ChatGPT / MCP","GitHub"):
        assert page in source
    assert "QThread.terminate" not in source and "run_manifest.json\").write" not in source
    assert "ResearchRunner" not in source and "BacktestWorker" not in source


def test_structured_rules_retain_private_payload_without_json_primary_editor():
    source=GUI.read_text(encoding="utf-8")
    tree=ast.parse(source)
    entry=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=="EntryRuleEditor")
    assert entry and "_payloads" in source and "Ordered Entry Rules" in source
    assert "Entry Rules (structured JSON array)" not in source
