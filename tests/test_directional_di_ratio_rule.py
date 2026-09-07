from types import SimpleNamespace

import numpy as np
import pytest

from crypto_strategy_core.candles import (
    directional_di_ratio,
    directional_rule_evidence,
)
from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.rule_strategy_builder import (
    EVIDENCE_GROUPS,
    EVIDENCE_LABELS,
    _evidence_menu_paths,
)
from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)


def test_directional_di_ratio_is_registered_and_exposed_in_builder():
    assert "DIRECTIONAL_DI_RATIO" in RULE_INDICATORS
    assert EVIDENCE_LABELS["DIRECTIONAL_DI_RATIO"] == "Directional DI Ratio"
    directional_group = dict(EVIDENCE_GROUPS)["Directional / DI"]
    assert "DIRECTIONAL_DI_RATIO" in directional_group
    assert directional_group.index("DIRECTIONAL_DI_RATIO") > directional_group.index(
        "DIRECTIONAL_DI"
    )
    assert _evidence_menu_paths()["DIRECTIONAL_DI_RATIO"] == ("Directional / DI",)


def test_directional_di_ratio_uses_trade_side_and_rejects_undefined_denominator():
    assert directional_di_ratio(30.0, 20.0) == pytest.approx(1.5)
    assert directional_di_ratio(20.0, 30.0) == pytest.approx(2.0 / 3.0)
    assert np.isnan(directional_di_ratio(30.0, 0.0))
    assert np.isnan(directional_di_ratio(np.nan, 20.0))


def test_shared_directional_rule_evidence_projects_ratio_by_side():
    plus = np.array([30.0, 20.0])
    minus = np.array([20.0, 30.0])

    long_evidence = directional_rule_evidence(
        plus,
        minus,
        index=0,
        lookback=1,
        side="LONG",
    )
    short_evidence = directional_rule_evidence(
        plus,
        minus,
        index=0,
        lookback=1,
        side="SHORT",
    )

    assert long_evidence["DIRECTIONAL_DI_RATIO"] == pytest.approx(1.5)
    assert short_evidence["DIRECTIONAL_DI_RATIO"] == pytest.approx(2.0 / 3.0)


def test_native_rule_runtime_uses_candidate_side_ratio():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.plus_di_values = np.array([30.0, 20.0])
    engine.minus_di_values = np.array([20.0, 30.0])
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "DIRECTIONAL_DI_RATIO"
    ) == pytest.approx(1.5)
    assert engine._strategy_profile_rule_value(
        0, "SHORT", profile, "DIRECTIONAL_DI_RATIO"
    ) == pytest.approx(2.0 / 3.0)
    assert engine._strategy_profile_rule_value(
        1, "SHORT", profile, "DIRECTIONAL_DI_RATIO"
    ) == pytest.approx(1.5)


def test_legacy_rule_runtime_keeps_directional_ratio_parity():
    engine = object.__new__(BacktestEngine)
    engine.plus_di_values = np.array([30.0, 20.0])
    engine.minus_di_values = np.array([20.0, 30.0])
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "DIRECTIONAL_DI_RATIO"
    ) == pytest.approx(1.5)
    assert engine._strategy_profile_rule_value(
        1, "SHORT", profile, "DIRECTIONAL_DI_RATIO"
    ) == pytest.approx(1.5)
