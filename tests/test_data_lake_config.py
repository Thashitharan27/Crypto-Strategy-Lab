from __future__ import annotations

from crypto_strategy_lab.data_lake_config import build_data_lake_backtest_config, normalize_data_lake_config


def test_data_lake_config_does_not_require_csv_paths() -> None:
    config = build_data_lake_backtest_config(
        {
            "config_version": 2,
            "market_symbol": "BTCUSDT",
            "strategy_timeframe_minutes": 240,
            "intrabar_timeframe_minutes": 1,
            "use_intrabar_data": True,
            "telemetry_interval_minutes": 240,
            "market_regime_method": "BTC_STRUCTURAL",
        }
    )

    assert config.strategy_timeframe_minutes == 240
    assert config.intrabar_timeframe_minutes == 1
    assert config.market_regime_method == "BTC_STRUCTURAL"
    assert str(config.input_csv) == "__DATA_LAKE_STRATEGY__"
    assert config.intrabar_csv is None
    assert config.structural_regime_benchmark_csv is None


def test_data_lake_config_rejects_market_data_path_fields() -> None:
    try:
        normalize_data_lake_config(
            {
                "config_version": 2,
                "input_csv": "BTCUSDT_4h.csv",
            }
        )
    except ValueError as exc:
        assert "input_csv" in str(exc)
    else:
        raise AssertionError("Data Lake config accepted a legacy CSV path field")
