"""Existing committed native-v3 Data Lake config stays compatible with browser reader."""
from pathlib import Path

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.data_lake_config import load_data_lake_config


def test_committed_btcusdt_4h_smoke_config_parity():
    config_path = Path(__file__).resolve().parents[1] / "config" / "data_lake" / "BTCUSDT_4H_SMOKE.json"
    before = config_path.read_bytes()
    native = load_data_lake_config(config_path)
    native.validate()
    browser = read_research_config(config_path)
    assert browser == native.to_dict()
    assert browser["data"]["strategy_timeframe_minutes"] == 240
    assert browser["data"]["intrabar_timeframe_minutes"] == 1
    assert browser["features"]["market_regime_method"] == "BTC_STRUCTURAL"
    assert config_path.read_bytes() == before
