from pathlib import Path
import pytest
from config import RiskMode
from gui.config_logic import parse_percentage, build_backtest_config, save_config_json, load_config_json


def base(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("timestamp,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n")
    return {"input_csv": str(csv), "output_dir": str(tmp_path / "out")}


def test_percent_conversions():
    assert parse_percentage("0.5%") == pytest.approx(0.005)
    assert parse_percentage("0.05%") == pytest.approx(0.0005)


def test_atr_mode_creates_config(tmp_path):
    cfg = build_backtest_config({**base(tmp_path), "risk_mode": "ATR", "atr_period": 14, "atr_multiplier": 1.5})
    assert cfg.risk_mode == RiskMode.ATR
    assert cfg.atr_period == 14
    assert cfg.atr_multiplier == pytest.approx(1.5)


def test_percentage_mode_creates_config(tmp_path):
    cfg = build_backtest_config({**base(tmp_path), "risk_mode": "PERCENT", "percent_r": parse_percentage("0.20%")})
    assert cfg.risk_mode == RiskMode.PERCENT
    assert cfg.percent_r == pytest.approx(0.002)


def test_fixed_mode_creates_config(tmp_path):
    cfg = build_backtest_config({**base(tmp_path), "risk_mode": "FIXED", "fixed_r": 100})
    assert cfg.risk_mode == RiskMode.FIXED
    assert cfg.fixed_r == pytest.approx(100)


def test_invalid_values_rejected(tmp_path):
    with pytest.raises(ValueError, match="SL multiple"):
        build_backtest_config({**base(tmp_path), "sl_mult": 0})
    with pytest.raises(ValueError, match="Risk per leg"):
        build_backtest_config({**base(tmp_path), "risk_per_leg": 1})


def test_saved_configuration_loads_correctly(tmp_path):
    path = tmp_path / "cfg.json"
    save_config_json(path, {**base(tmp_path), "risk_mode": "FIXED", "fixed_r": 123, "risk_per_leg": 0.005})
    loaded = load_config_json(path)
    cfg = build_backtest_config(loaded)
    assert cfg.fixed_r == pytest.approx(123)
    assert cfg.risk_per_leg == pytest.approx(0.005)

def test_gui_passes_selected_intrabar_csv_and_enabled_flag(tmp_path):
    strategy = tmp_path / "strategy.csv"
    intrabar = tmp_path / "intrabar.csv"
    content = "timestamp,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n"
    strategy.write_text(content)
    intrabar.write_text(content)
    cfg = build_backtest_config({**base(tmp_path), "input_csv": str(strategy), "intrabar_csv": str(intrabar), "use_intrabar_data": True})
    assert cfg.intrabar_csv == intrabar
    assert cfg.use_intrabar_data is True
    assert cfg.intrabar_timeframe_minutes == 1
