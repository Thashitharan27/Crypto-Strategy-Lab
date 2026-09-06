from crypto_strategy_lab.gui.rule_strategy_builder import (
    EVIDENCE_GROUPS,
    EVIDENCE_LABELS,
    EVIDENCE_MENU_TREE,
    _evidence_menu_paths,
)
from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS


def test_directional_di_is_a_separate_directional_builder_option():
    assert EVIDENCE_LABELS["DIRECTIONAL_DI"] == "Directional DI"
    directional_group = dict(EVIDENCE_GROUPS)["Directional / DI"]
    assert "DIRECTIONAL_DI" in directional_group
    assert "DIRECTIONAL_DI_CHANGE" in directional_group
    assert directional_group.index("DIRECTIONAL_DI") != directional_group.index(
        "DIRECTIONAL_DI_CHANGE"
    )


def test_evidence_picker_uses_compact_top_level_categories():
    assert tuple(label for label, _children in EVIDENCE_MENU_TREE) == (
        "Directional / DI",
        "Trend & Volatility",
        "Momentum & Price",
        "Mean Reversion",
        "Futures",
        "Support & Resistance",
    )

    futures = dict(EVIDENCE_MENU_TREE)["Futures"]
    assert tuple(label for label, _children in futures) == (
        "Open Interest & Positioning",
        "Funding",
        "Basis / Premium",
        "Taker Flow",
    )


def test_every_rule_evidence_has_a_searchable_category_path():
    paths = _evidence_menu_paths()
    assert set(paths) == set(RULE_INDICATORS)
    assert paths["MR_TRADE_STRETCH_ATR"] == ("Mean Reversion", "Entry Location")
    assert paths["MR_SIGNAL"] == ("Mean Reversion", "Confirmation")
    assert paths["MR_STATE"] == ("Mean Reversion", "Advanced")
    assert paths["FUNDING_RATE_BPS"] == ("Futures", "Funding")
    assert paths["OI_CHANGE_PCT_1H"] == ("Futures", "Open Interest & Positioning")
    assert paths["SR_SUPPORT_STATE"] == (
        "Support & Resistance",
        "Advanced S/R",
    )
    assert paths["SR_RESISTANCE_TEST_COUNT"] == (
        "Support & Resistance",
        "Advanced S/R",
    )
    assert paths["SR_BARS_SINCE_SUPPORT_TEST"] == (
        "Support & Resistance",
        "Advanced S/R",
    )
    assert EVIDENCE_LABELS["SR_SUPPORT_TEST_COUNT"] == "S/R — Support Test Count"
    assert (
        EVIDENCE_LABELS["SR_BARS_SINCE_RESISTANCE_TEST"]
        == "S/R — Bars Since Resistance Test"
    )
