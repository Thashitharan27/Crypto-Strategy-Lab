"""One-shot Stage 19 migration: remove the retired strategy_csv alias."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected Stage 19 cleanup text not found in {path}: {old!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "crypto_strategy_lab/config.py",
    '    strategy_csv: Path = Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv")\n',
    "",
)
replace_exact(
    "crypto_strategy_lab/config.py",
    '        if self.input_csv != Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv") and self.strategy_csv == Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv"):\n            object.__setattr__(self, "strategy_csv", self.input_csv)\n',
    "",
)
replace_exact(
    "crypto_strategy_lab/gui/config_logic.py",
    '    "strategy_csv": "C:/CryptoBots/Binance Market Data/futures/usdm/BTCUSDT_15m.csv",\n',
    "",
)
replace_exact(
    "crypto_strategy_lab/gui/config_logic.py",
    '        strategy_path = values.get("strategy_csv") or values.get("input_csv")\n',
    '        strategy_path = values.get("input_csv")\n',
)
replace_exact(
    "crypto_strategy_lab/gui/config_logic.py",
    '        strategy_csv=Path(merged.get("strategy_csv") or merged["input_csv"]),\n',
    "",
)
replace_exact(
    "crypto_strategy_lab/loader.py",
    'load_ohlcv_csv(str(config.strategy_csv), config.timestamp_unit, config.strategy_timeframe_minutes, "Strategy data", True)',
    'load_ohlcv_csv(str(config.input_csv), config.timestamp_unit, config.strategy_timeframe_minutes, "Strategy data", True)',
)
replace_exact(
    "tools/stage19_audit_legacy_config.py",
    'LEGACY = {\n',
    'LEGACY = {\n    "strategy_csv",\n',
)

print("Removed retired strategy_csv alias from current configuration and loader.")
