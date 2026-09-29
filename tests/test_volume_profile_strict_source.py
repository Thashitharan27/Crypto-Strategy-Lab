import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.volume_profile import VolumeProfileMixin


class Probe(VolumeProfileMixin):
    pass


def test_volume_profile_rule_fails_closed_without_exact_aggtrade_context():
    probe = Probe()
    probe.config = type("C", (), {"strategy_timeframe_minutes": 15})()
    probe._prepared_research_raw_value = lambda *args: np.nan
    with pytest.raises(RuntimeError, match="OHLCV fallback is disabled"):
        probe._volume_profile_rule_value(
            10, "LONG", "VP_HVN_STRENGTH", 15
        )


def test_absorption_rule_fails_closed_on_unknown_aggtrade_coverage():
    probe = Probe()
    probe.config = type("C", (), {"strategy_timeframe_minutes": 15})()
    probe._prepared_research_raw_value = lambda *args: "UNKNOWN"
    with pytest.raises(RuntimeError, match="complete the aggTrades archive"):
        probe._volume_profile_rule_value(
            10, "LONG", "VP_BUY_ABSORPTION", 15
        )


def test_absorption_rule_uses_aggtrade_flow_state():
    probe = Probe()
    probe.config = type("C", (), {"strategy_timeframe_minutes": 15})()
    probe._prepared_research_raw_value = lambda *args: "BUY_ABSORPTION"
    assert probe._volume_profile_rule_value(
        10, "LONG", "VP_BUY_ABSORPTION", 15
    ) == 1.0
    assert probe._volume_profile_rule_value(
        10, "LONG", "VP_SELL_ABSORPTION", 15
    ) == 0.0
