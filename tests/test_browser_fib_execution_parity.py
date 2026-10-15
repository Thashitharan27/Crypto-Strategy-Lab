"""Verify Fibonacci and execution options survive native->browser read-only serialization."""
from dataclasses import replace
import json

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_fibonacci_and_execution_profile_config_snapshot_exact(tmp_path):
    native = ResearchRunConfig()
    changed = replace(
        native,
        features=replace(native.features,
            fib_third_retest_entry=True,
            fib_candle_confirmation_enabled=True,
            fib_candle_engulfing=False),
        execution=replace(native.execution,
            ema_320_flip_signals=True,
            ema_cross_entry_confirmation_enabled=True),
    )
    changed.validate()
    path = tmp_path / "fib_execution.json"
    path.write_text(json.dumps(changed.to_dict(), allow_nan=False), encoding="utf-8")
    before = path.read_bytes()
    projected = read_research_config(path)
    assert projected == changed.to_dict()
    assert projected["features"]["fib_third_retest_entry"] is True
    assert projected["features"]["fib_candle_confirmation_enabled"] is True
    assert projected["features"]["fib_candle_engulfing"] is False
    assert projected["execution"]["ema_320_flip_signals"] is True
    assert projected["execution"]["ema_cross_entry_confirmation_enabled"] is True
    assert projected["strategy"]["profiles"] == changed.to_dict()["strategy"]["profiles"]
    assert projected["execution"]["profiles"] == changed.to_dict()["execution"]["profiles"]
    assert path.read_bytes() == before
