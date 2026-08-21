from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pandas as pd


def _load_tool():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "data_lake_backtest_parity.py"
    spec = importlib.util.spec_from_file_location("data_lake_backtest_parity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_period_is_recovered_from_saved_run_log(tmp_path: Path) -> None:
    tool = _load_tool()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config_path = run_dir / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    (run_dir / "log.txt").write_text(
        "Loaded 10 strategy candles\n"
        "Period: 2026-01-01 00:00:00+00:00 to 2026-01-02 20:00:00+00:00\n",
        encoding="utf-8",
    )

    start, end = tool._period_from_saved_run(config_path, 240)

    assert start == pd.Timestamp("2026-01-01T00:00:00Z")
    assert end == pd.Timestamp("2026-01-03T00:00:00Z")


def test_raw_archive_reference_parses_headerless_binance_zip(tmp_path: Path) -> None:
    tool = _load_tool()
    archive = tmp_path / "BTCUSDT-4h-2026-01.zip"
    csv_text = (
        "1767225600000,100,103,99,102,10,1767239999999,0,1,0,0,0\n"
        "1767240000000,102,104,101,103,11,1767254399999,0,1,0,0,0\n"
    )
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("BTCUSDT-4h-2026-01.csv", csv_text)

    frame = tool._raw_reference_ohlcv(
        [SimpleNamespace(path=archive)],
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T08:00:00Z"),
    )

    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(frame) == 2
    assert frame.loc[0, "timestamp"] == pd.Timestamp("2026-01-01T00:00:00Z")
    assert frame.loc[1, "close"] == 103.0
