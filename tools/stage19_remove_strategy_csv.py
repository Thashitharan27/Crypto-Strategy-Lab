"""One-shot Stage 19 migration: remove the retired strategy_csv alias everywhere."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_if_present(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return
    target.write_text(text.replace(old, new), encoding="utf-8")


# Configuration / loading boundary.
replace_if_present(
    "crypto_strategy_lab/config.py",
    '    strategy_csv: Path = Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv")\n',
    "",
)
replace_if_present(
    "crypto_strategy_lab/config.py",
    '        if self.input_csv != Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv") and self.strategy_csv == Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv"):\n            object.__setattr__(self, "strategy_csv", self.input_csv)\n',
    "",
)
replace_if_present(
    "crypto_strategy_lab/gui/config_logic.py",
    '    "strategy_csv": "C:/CryptoBots/Binance Market Data/futures/usdm/BTCUSDT_15m.csv",\n',
    "",
)
replace_if_present(
    "crypto_strategy_lab/gui/config_logic.py",
    '        strategy_path = values.get("strategy_csv") or values.get("input_csv")\n',
    '        strategy_path = values.get("input_csv")\n',
)
replace_if_present(
    "crypto_strategy_lab/gui/config_logic.py",
    '        strategy_csv=Path(merged.get("strategy_csv") or merged["input_csv"]),\n',
    "",
)
replace_if_present(
    "crypto_strategy_lab/loader.py",
    'load_ohlcv_csv(str(config.strategy_csv), config.timestamp_unit, config.strategy_timeframe_minutes, "Strategy data", True)',
    'load_ohlcv_csv(str(config.input_csv), config.timestamp_unit, config.strategy_timeframe_minutes, "Strategy data", True)',
)

# GUI save/load.
replace_if_present(
    "crypto_strategy_lab/gui/main_window.py",
    'values.get("strategy_csv") or values.get("input_csv") or ""',
    'values.get("input_csv") or ""',
)
replace_if_present(
    "crypto_strategy_lab/gui/main_window.py",
    '            "input_csv": self.input_csv.text(), "strategy_csv": self.input_csv.text(),\n',
    '            "input_csv": self.input_csv.text(),\n',
)

# Engine / reports / CLI.
replace_if_present(
    "crypto_strategy_lab/engine.py",
    '            strategy_path = Path(self.config.strategy_csv)\n',
    '            strategy_path = Path(self.config.input_csv)\n',
)
replace_if_present(
    "crypto_strategy_lab/output_manager.py",
    '    stem = Path(config.strategy_csv or config.input_csv).stem.upper()\n',
    '    stem = Path(config.input_csv).stem.upper()\n',
)
replace_if_present(
    "crypto_strategy_lab/output_manager.py",
    '        f"Strategy CSV: {config.strategy_csv}",\n',
    '        f"Strategy CSV: {config.input_csv}",\n',
)
replace_if_present(
    "crypto_strategy_lab/report_workbooks.py",
    '("Symbol", getattr(config, "strategy_csv", None) and Path(config.strategy_csv).stem),',
    '("Symbol", getattr(config, "input_csv", None) and Path(config.input_csv).stem),',
)
replace_if_present(
    "crypto_strategy_lab/cli.py",
    '    parser.add_argument("--input", type=Path, help="Backward-compatible strategy CSV path")\n    parser.add_argument("--strategy-input", type=Path, dest="strategy_csv")\n',
    '    parser.add_argument("--input", type=Path, help="Strategy CSV path")\n',
)

# Make strategy_csv explicitly retired in the audit once.
audit = ROOT / "tools/stage19_audit_legacy_config.py"
text = audit.read_text(encoding="utf-8")
if '    "strategy_csv",\n' not in text:
    text = text.replace('LEGACY = {\n', 'LEGACY = {\n    "strategy_csv",\n')
    audit.write_text(text, encoding="utf-8")

print("Retired strategy_csv alias removed from production configuration and code paths.")
