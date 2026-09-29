from types import SimpleNamespace

import pandas as pd
import pytest

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_VALUE_CODES,
    new_rule,
    uses_detailed_trade_flow_rules,
    uses_order_book_rules,
)


TRADE_RULES = {
    "AGG_TRADE_DELTA_PCT_1M",
    "AGG_TRADE_DELTA_PCT_5M",
    "AGG_TRADE_DELTA_PCT_15M",
    "AGG_TRADE_DELTA_PCT_1H",
    "AGG_CVD_1H",
    "AGG_CVD_CHANGE_1BAR",
    "AGG_TRADE_INTENSITY_CHANGE",
    "AGG_TRADE_INTENSITY_1M",
    "AGG_TRADE_INTENSITY_5M",
    "AGG_TRADE_INTENSITY_15M",
    "AGG_TRADE_INTENSITY_1H",
    "AGG_LARGE_BUY_SHARE_15M",
    "AGG_LARGE_SELL_SHARE_15M",
    "AGG_TRADE_VWAP_DISTANCE_PCT_15M",
    "AGG_TRADE_VWAP_DISTANCE_PCT_1H",
    "AGG_CVD_PRICE_STATE",
    "AGG_FLOW_RESPONSE_STATE",
}

BOOK_RULES = {
    "BOOK_SPREAD_BPS",
    "BOOK_IMBALANCE_L1",
    "BOOK_MICROPRICE_OFFSET_BPS",
    "BOOK_IMBALANCE_CHANGE",
    "BOOK_MICROPRICE_OFFSET_CHANGE_BPS",
    "BOOK_PRESSURE_STATE",
}


def _engine():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.research_features = {
        "trade_flow_context": pd.DataFrame(
            {
                "trade_delta_pct_1m": [0.10],
                "trade_delta_pct_5m": [0.12],
                "trade_delta_pct_15m": [0.20],
                "trade_delta_pct_1h": [0.25],
                "cvd_1h": [125.0],
                "cvd_change_1bar": [20.0],
                "trade_intensity_change": [0.75],
                "trade_intensity_1m": [120.0],
                "trade_intensity_5m": [100.0],
                "trade_intensity_15m": [90.0],
                "trade_intensity_1h": [80.0],
                "large_buy_share_15m": [0.70],
                "large_sell_share_15m": [0.30],
                "trade_vwap_distance_pct_15m": [0.004],
                "trade_vwap_distance_pct_1h": [0.008],
                "cvd_price_state": ["BULLISH_DIVERGENCE"],
                "flow_response_state": ["BUY_ABSORPTION"],
            }
        ),
        "order_book_context": pd.DataFrame(
            {
                "book_spread_bps": [0.8],
                "book_imbalance_l1": [0.35],
                "book_microprice_offset_bps": [0.4],
                "book_imbalance_l1_change": [0.15],
                "book_microprice_offset_change_bps": [0.2],
                "book_pressure_state": ["BULLISH"],
            }
        ),
    }
    return engine


def test_microstructure_rule_ids_are_registered():
    assert TRADE_RULES <= set(RULE_INDICATORS)
    assert BOOK_RULES <= set(RULE_INDICATORS)


def test_aggtrade_numeric_and_categorical_values_are_rule_ready():
    engine = _engine()
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "AGG_TRADE_DELTA_PCT_15M"
    ) == pytest.approx(0.20)
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "AGG_CVD_PRICE_STATE"
    ) == CATEGORICAL_VALUE_CODES["AGG_CVD_PRICE_STATE"]["BULLISH_DIVERGENCE"]
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "AGG_FLOW_RESPONSE_STATE"
    ) == CATEGORICAL_VALUE_CODES["AGG_FLOW_RESPONSE_STATE"]["BUY_ABSORPTION"]


def test_book_ticker_numeric_and_pressure_values_are_rule_ready():
    engine = _engine()
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "BOOK_IMBALANCE_L1"
    ) == pytest.approx(0.35)
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "BOOK_PRESSURE_STATE"
    ) == CATEGORICAL_VALUE_CODES["BOOK_PRESSURE_STATE"]["BULLISH"]


def test_rule_dependency_detection_ignores_muted_groups():
    trade = new_rule(kind="VETO", evidence="AGG_CVD_PRICE_STATE")
    book = new_rule(kind="REQUIRED", evidence="BOOK_PRESSURE_STATE")
    assert uses_detailed_trade_flow_rules((trade,))
    assert uses_order_book_rules((book,))

    trade["group_enabled"] = False
    book["group_enabled"] = False
    assert not uses_detailed_trade_flow_rules((trade,))
    assert not uses_order_book_rules((book,))
