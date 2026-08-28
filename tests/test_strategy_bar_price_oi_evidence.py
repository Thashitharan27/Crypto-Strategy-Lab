from types import SimpleNamespace

import pandas as pd

from crypto_strategy_lab.strategy_bar_price_oi_evidence import (
    EVIDENCE_ID,
    EVIDENCE_LABEL,
    RULE_VALUES,
    install_strategy_bar_price_oi_evidence,
)

# Production installs this before the active GUI/native rule modules are used.
install_strategy_bar_price_oi_evidence()

from crypto_strategy_lab import rule_native_engine, strategy_profiles, strategy_rule_model
from crypto_strategy_lab.gui import rule_strategy_builder
from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
from crypto_strategy_lab.strategy_rule_model import compile_profiles, normalize_rule


def _menu_contains(items, target):
    for item in items:
        if isinstance(item, str):
            if item == target:
                return True
            continue
        _label, children = item
        if _menu_contains(children, target):
            return True
    return False


def test_strategy_bar_price_oi_evidence_is_registered_and_idempotent():
    install_strategy_bar_price_oi_evidence()
    install_strategy_bar_price_oi_evidence()

    assert strategy_profiles.RULE_INDICATORS.count(EVIDENCE_ID) == 1
    assert strategy_rule_model.RULE_INDICATORS.count(EVIDENCE_ID) == 1
    assert strategy_rule_model.rule_value_options(EVIDENCE_ID) == RULE_VALUES
    assert strategy_rule_model.CATEGORICAL_VALUE_CODES[EVIDENCE_ID]["UNKNOWN"] == 5.0
    assert strategy_rule_model.CATEGORICAL_VALUE_CODES[EVIDENCE_ID]["FLAT_OR_MIXED"] == 6.0

    assert rule_strategy_builder.EVIDENCE_LABELS[EVIDENCE_ID] == EVIDENCE_LABEL
    positioning = dict(rule_strategy_builder.EVIDENCE_GROUPS)[
        "Futures — Open Interest & Positioning"
    ]
    assert positioning[0] == EVIDENCE_ID
    assert positioning.count(EVIDENCE_ID) == 1
    assert _menu_contains(rule_strategy_builder.EVIDENCE_MENU_TREE, EVIDENCE_ID)


def test_strategy_bar_price_oi_reads_price_oi_state_not_one_hour_state():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.research_features = {
        "futures_positioning": pd.DataFrame(
            {
                "price_oi_state": ["PRICE_DOWN_OI_DOWN"],
                "oi_vs_price_state_1h": ["PRICE_UP_OI_UP"],
            }
        )
    }
    profile = SimpleNamespace()

    assert rule_native_engine._RESEARCH_CATEGORICAL_FIELDS[EVIDENCE_ID] == (
        "futures_positioning",
        "price_oi_state",
    )
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, EVIDENCE_ID
    ) == 4.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "OI_VS_PRICE_STATE_1H"
    ) == 1.0


def test_doge_bull_vetoes_compile_as_exact_combined_states():
    bull_long = normalize_rule(
        {
            "kind": "VETO",
            "evidence": EVIDENCE_ID,
            "operator": "IS",
            "value": "PRICE_UP_OI_UP",
            "regime": "BULL",
            "side": "LONG",
        }
    )
    bull_short = normalize_rule(
        {
            "kind": "VETO",
            "evidence": EVIDENCE_ID,
            "operator": "IS",
            "value": "PRICE_DOWN_OI_DOWN",
            "regime": "BULL",
            "side": "SHORT",
        }
    )

    profiles, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=("BULL_LONG", "BULL_SHORT"),
        veto_rules=(bull_long, bull_short),
    )

    long_rules = profiles["bull_long"].entry_rules
    short_rules = profiles["bull_short"].entry_rules
    assert len(long_rules) == 1
    assert len(short_rules) == 1
    assert long_rules[0]["indicator"] == EVIDENCE_ID
    assert long_rules[0]["condition"] == "INSIDE"
    assert long_rules[0]["minimum"] == long_rules[0]["maximum"] == 1.0
    assert short_rules[0]["indicator"] == EVIDENCE_ID
    assert short_rules[0]["condition"] == "INSIDE"
    assert short_rules[0]["minimum"] == short_rules[0]["maximum"] == 4.0


def test_requested_strategy_bar_choices_are_exposed_without_recreating_and_logic():
    assert strategy_rule_model.rule_operator_options(EVIDENCE_ID) == ("IS", "IS_NOT")
    assert strategy_rule_model.rule_value_options(EVIDENCE_ID) == (
        "PRICE_UP_OI_UP",
        "PRICE_UP_OI_DOWN",
        "PRICE_DOWN_OI_UP",
        "PRICE_DOWN_OI_DOWN",
        "UNKNOWN",
    )
