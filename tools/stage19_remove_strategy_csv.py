"""One-shot Stage 19 hard-cleanup migration.

This helper is temporary and will be removed before the PR is marked ready.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_if_present(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return
    target.write_text(text.replace(old, new), encoding="utf-8")


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    start_i = text.find(start)
    if start_i < 0:
        return
    end_i = text.find(end, start_i)
    if end_i < 0:
        raise SystemExit(f"Stage 19 end marker not found in {path}: {end!r}")
    target.write_text(text[:start_i] + replacement + text[end_i:], encoding="utf-8")


# Remove the retired strategy_csv alias from every production boundary.
for path, old, new in (
    ("crypto_strategy_lab/config.py", '    strategy_csv: Path = Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv")\n', ""),
    ("crypto_strategy_lab/config.py", '        if self.input_csv != Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv") and self.strategy_csv == Path(r"C:\\CryptoBots\\Binance Market Data\\futures\\usdm\\BTCUSDT_15m.csv"):\n            object.__setattr__(self, "strategy_csv", self.input_csv)\n', ""),
    ("crypto_strategy_lab/gui/config_logic.py", '    "strategy_csv": "C:/CryptoBots/Binance Market Data/futures/usdm/BTCUSDT_15m.csv",\n', ""),
    ("crypto_strategy_lab/gui/config_logic.py", '        strategy_path = values.get("strategy_csv") or values.get("input_csv")\n', '        strategy_path = values.get("input_csv")\n'),
    ("crypto_strategy_lab/gui/config_logic.py", '        strategy_csv=Path(merged.get("strategy_csv") or merged["input_csv"]),\n', ""),
    ("crypto_strategy_lab/loader.py", 'load_ohlcv_csv(str(config.strategy_csv), config.timestamp_unit, config.strategy_timeframe_minutes, "Strategy data", True)', 'load_ohlcv_csv(str(config.input_csv), config.timestamp_unit, config.strategy_timeframe_minutes, "Strategy data", True)'),
    ("crypto_strategy_lab/gui/main_window.py", 'values.get("strategy_csv") or values.get("input_csv") or ""', 'values.get("input_csv") or ""'),
    ("crypto_strategy_lab/gui/main_window.py", '            "input_csv": self.input_csv.text(), "strategy_csv": self.input_csv.text(),\n', '            "input_csv": self.input_csv.text(),\n'),
    ("crypto_strategy_lab/engine.py", '            strategy_path = Path(self.config.strategy_csv)\n', '            strategy_path = Path(self.config.input_csv)\n'),
    ("crypto_strategy_lab/output_manager.py", '    stem = Path(config.strategy_csv or config.input_csv).stem.upper()\n', '    stem = Path(config.input_csv).stem.upper()\n'),
    ("crypto_strategy_lab/output_manager.py", '        f"Strategy CSV: {config.strategy_csv}",\n', '        f"Strategy CSV: {config.input_csv}",\n'),
    ("crypto_strategy_lab/report_workbooks.py", '("Symbol", getattr(config, "strategy_csv", None) and Path(config.strategy_csv).stem),', '("Symbol", getattr(config, "input_csv", None) and Path(config.input_csv).stem),'),
):
    replace_if_present(path, old, new)

# Output naming/reporting is profile-only.
replace_if_present(
    "crypto_strategy_lab/output_manager.py",
    '''def _profile_mode_label(config: BacktestConfig) -> str | None:\n    if not config.enable_strategy_profiles:\n        return None\n    labels = {\n        "ISOLATED_PROFILES": "PROFILES-ISOLATED",\n        "COMBINED_SHARED_CAPITAL": "PROFILES-COMBINED",\n        "BOTH": "PROFILES-BOTH",\n    }\n    return labels.get(config.strategy_profile_run_mode, f"PROFILES-{_safe_part(config.strategy_profile_run_mode)}")\n''',
    '''def _profile_mode_label(config: BacktestConfig) -> str:\n    labels = {\n        "ISOLATED_PROFILES": "PROFILES-ISOLATED",\n        "COMBINED_SHARED_CAPITAL": "PROFILES-COMBINED",\n        "BOTH": "PROFILES-BOTH",\n    }\n    return labels.get(config.strategy_profile_run_mode, f"PROFILES-{_safe_part(config.strategy_profile_run_mode)}")\n''',
)
replace_between("crypto_strategy_lab/output_manager.py", "def _stop_label(config: BacktestConfig) -> str:\n", "def infer_symbol(config: BacktestConfig) -> str:\n", "")
replace_if_present(
    "crypto_strategy_lab/output_manager.py",
    '''    stop, target = (\n        _profile_exit_labels(config)\n        if config.enable_strategy_profiles\n        else (_stop_label(config), _target_label(config))\n    )\n''',
    '    stop, target = _profile_exit_labels(config)\n',
)
replace_if_present(
    "crypto_strategy_lab/output_manager.py",
    '''    profile_mode = _profile_mode_label(config)\n    if profile_mode:\n        parts.append(profile_mode)\n''',
    '    parts.append(_profile_mode_label(config))\n',
)
replace_between(
    "crypto_strategy_lab/output_manager.py",
    "def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:\n",
    "def compatible_resample_freq(freq: str) -> str:\n",
    '''def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:\n    enabled_profiles = {key: profile for key, profile in config.strategy_profiles.items() if profile.enabled}\n    trailing_profiles = [key for key, profile in enabled_profiles.items() if profile.trailing_enabled or profile.r_step_trailing_enabled]\n    break_even_profiles = [key for key, profile in enabled_profiles.items() if profile.break_even_enabled]\n    timeout_profiles = [key for key, profile in enabled_profiles.items() if profile.timeout_enabled]\n    lines = [\n        "Backtest Run Information",\n        "========================",\n        f"Output folder: {run_dir.resolve()}",\n        f"Run name: {config.run_name or '(none)'}",\n        f"Strategy CSV: {config.input_csv}",\n        f"Intrabar CSV: {config.intrabar_csv if config.use_intrabar_data else '(disabled)'}",\n        f"Symbol: {infer_symbol(config)}",\n        f"Strategy timeframe: {config.strategy_timeframe_minutes}m",\n        f"Risk mode: {config.risk_mode.value}",\n        f"ATR period/multiplier: {config.atr_period} / {config.atr_multiplier}",\n        "Strategy Profiles: " + (", ".join(enabled_profiles) if enabled_profiles else "none enabled"),\n        f"Strategy Profile run mode: {config.strategy_profile_run_mode}",\n        "Trailing profiles: " + (", ".join(trailing_profiles) if trailing_profiles else "none"),\n        "Break-even profiles: " + (", ".join(break_even_profiles) if break_even_profiles else "none"),\n        "Timeout profiles: " + (", ".join(timeout_profiles) if timeout_profiles else "none"),\n        f"Partial intrabar ordering: {'STOP_FIRST' if config.tie_policy.value == 'PESSIMISTIC' else 'TP1_THEN_TP2_THEN_STOP'}",\n        f"Initial equity: {config.initial_equity}",\n        f"Total pairs: {summary.get('total_pairs')}",\n        f"Ending equity: {summary.get('ending_equity')}",\n        f"Total return %: {summary.get('total_return_percentage')}",\n    ]\n    (run_dir / "run_info.txt").write_text("\\n".join(lines) + "\\n")\n\n\n''',
)

# GUI worker always uses the current Strategy Profile contract. Remove legacy
# experiment imports, condition flags, random-entry reports, and global direction.
replace_if_present(
    "crypto_strategy_lab/gui/worker.py",
    "from crypto_strategy_lab.random_entry import decisions_frame, random_analysis, run_batch, comparison_row\n",
    "",
)
replace_if_present(
    "crypto_strategy_lab/gui/worker.py",
    "from crypto_strategy_lab.config import EntryTimingMode\n",
    "",
)
replace_if_present(
    "crypto_strategy_lab/gui/worker.py",
    '            if self.config.enable_strategy_profiles and self.config.strategy_profile_run_mode=="ISOLATED_PROFILES":\n',
    '            if self.config.strategy_profile_run_mode=="ISOLATED_PROFILES":\n',
)
replace_if_present(
    "crypto_strategy_lab/gui/worker.py",
    '            summary.update({"trade_direction": self.config.trade_direction.value, "use_intrabar_data": self.config.use_intrabar_data, "intrabar_csv": str(self.config.intrabar_csv) if self.config.intrabar_csv else None, "strategy_timeframe": self.config.strategy_timeframe_minutes, "intrabar_timeframe": self.config.intrabar_timeframe_minutes, "atr_period": self.config.atr_period, "atr_multiplier": self.config.atr_multiplier})\n',
    '            summary.update({"strategy_profile_run_mode": self.config.strategy_profile_run_mode, "use_intrabar_data": self.config.use_intrabar_data, "intrabar_csv": str(self.config.intrabar_csv) if self.config.intrabar_csv else None, "strategy_timeframe": self.config.strategy_timeframe_minutes, "intrabar_timeframe": self.config.intrabar_timeframe_minutes, "atr_period": self.config.atr_period, "atr_multiplier": self.config.atr_multiplier})\n',
)
replace_if_present(
    "crypto_strategy_lab/gui/worker.py",
    '            if self.config.enable_strategy_profiles and self.config.strategy_profile_run_mode == "BOTH":\n',
    '            if self.config.strategy_profile_run_mode == "BOTH":\n',
)
replace_between(
    "crypto_strategy_lab/gui/worker.py",
    "            if engine.random_entry_active:\n",
    "            if self.config.save_feature_analysis_reports:\n",
    "",
)

# Make strategy_csv explicitly retired in the audit once.
audit = ROOT / "tools/stage19_audit_legacy_config.py"
text = audit.read_text(encoding="utf-8")
if '    "strategy_csv",\n' not in text:
    text = text.replace('LEGACY = {\n', 'LEGACY = {\n    "strategy_csv",\n')
    audit.write_text(text, encoding="utf-8")

print("Applied Stage 19 hard-cleanup migration batch.")
