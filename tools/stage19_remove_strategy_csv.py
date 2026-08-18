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


# Retire strategy_csv everywhere.
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

# Output manager is profile-only.
replace_if_present(
    "crypto_strategy_lab/output_manager.py",
    '''def _profile_mode_label(config: BacktestConfig) -> str | None:\n    if not config.enable_strategy_profiles:\n        return None\n    labels = {\n        "ISOLATED_PROFILES": "PROFILES-ISOLATED",\n        "COMBINED_SHARED_CAPITAL": "PROFILES-COMBINED",\n        "BOTH": "PROFILES-BOTH",\n    }\n    return labels.get(config.strategy_profile_run_mode, f"PROFILES-{_safe_part(config.strategy_profile_run_mode)}")\n''',
    '''def _profile_mode_label(config: BacktestConfig) -> str:\n    labels = {\n        "ISOLATED_PROFILES": "PROFILES-ISOLATED",\n        "COMBINED_SHARED_CAPITAL": "PROFILES-COMBINED",\n        "BOTH": "PROFILES-BOTH",\n    }\n    return labels.get(config.strategy_profile_run_mode, f"PROFILES-{_safe_part(config.strategy_profile_run_mode)}")\n''',
)
replace_between("crypto_strategy_lab/output_manager.py", "def _stop_label(config: BacktestConfig) -> str:\n", "def infer_symbol(config: BacktestConfig) -> str:\n", "")
replace_if_present("crypto_strategy_lab/output_manager.py", '''    stop, target = (\n        _profile_exit_labels(config)\n        if config.enable_strategy_profiles\n        else (_stop_label(config), _target_label(config))\n    )\n''', '    stop, target = _profile_exit_labels(config)\n')
replace_if_present("crypto_strategy_lab/output_manager.py", '''    profile_mode = _profile_mode_label(config)\n    if profile_mode:\n        parts.append(profile_mode)\n''', '    parts.append(_profile_mode_label(config))\n')
replace_between(
    "crypto_strategy_lab/output_manager.py",
    "def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:\n",
    "def compatible_resample_freq(freq: str) -> str:\n",
    '''def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:\n    enabled_profiles = {key: profile for key, profile in config.strategy_profiles.items() if profile.enabled}\n    trailing_profiles = [key for key, profile in enabled_profiles.items() if profile.trailing_enabled or profile.r_step_trailing_enabled]\n    break_even_profiles = [key for key, profile in enabled_profiles.items() if profile.break_even_enabled]\n    timeout_profiles = [key for key, profile in enabled_profiles.items() if profile.timeout_enabled]\n    lines = [\n        "Backtest Run Information",\n        "========================",\n        f"Output folder: {run_dir.resolve()}",\n        f"Run name: {config.run_name or '(none)'}",\n        f"Strategy CSV: {config.input_csv}",\n        f"Intrabar CSV: {config.intrabar_csv if config.use_intrabar_data else '(disabled)'}",\n        f"Symbol: {infer_symbol(config)}",\n        f"Strategy timeframe: {config.strategy_timeframe_minutes}m",\n        f"Risk mode: {config.risk_mode.value}",\n        f"ATR period/multiplier: {config.atr_period} / {config.atr_multiplier}",\n        "Strategy Profiles: " + (", ".join(enabled_profiles) if enabled_profiles else "none enabled"),\n        f"Strategy Profile run mode: {config.strategy_profile_run_mode}",\n        "Trailing profiles: " + (", ".join(trailing_profiles) if trailing_profiles else "none"),\n        "Break-even profiles: " + (", ".join(break_even_profiles) if break_even_profiles else "none"),\n        "Timeout profiles: " + (", ".join(timeout_profiles) if timeout_profiles else "none"),\n        f"Partial intrabar ordering: {'STOP_FIRST' if config.tie_policy.value == 'PESSIMISTIC' else 'TP1_THEN_TP2_THEN_STOP'}",\n        f"Initial equity: {config.initial_equity}",\n        f"Total pairs: {summary.get('total_pairs')}",\n        f"Ending equity: {summary.get('ending_equity')}",\n        f"Total return %: {summary.get('total_return_percentage')}",\n    ]\n    (run_dir / "run_info.txt").write_text("\\n".join(lines) + "\\n")\n\n\n''',
)

# GUI worker always uses Strategy Profiles; remove old random experiment paths.
replace_if_present("crypto_strategy_lab/gui/worker.py", "from crypto_strategy_lab.random_entry import decisions_frame, random_analysis, run_batch, comparison_row\n", "")
replace_if_present("crypto_strategy_lab/gui/worker.py", "from crypto_strategy_lab.config import EntryTimingMode\n", "")
replace_if_present("crypto_strategy_lab/gui/worker.py", '            if self.config.enable_strategy_profiles and self.config.strategy_profile_run_mode=="ISOLATED_PROFILES":\n', '            if self.config.strategy_profile_run_mode=="ISOLATED_PROFILES":\n')
replace_if_present("crypto_strategy_lab/gui/worker.py", '            summary.update({"trade_direction": self.config.trade_direction.value, "use_intrabar_data": self.config.use_intrabar_data, "intrabar_csv": str(self.config.intrabar_csv) if self.config.intrabar_csv else None, "strategy_timeframe": self.config.strategy_timeframe_minutes, "intrabar_timeframe": self.config.intrabar_timeframe_minutes, "atr_period": self.config.atr_period, "atr_multiplier": self.config.atr_multiplier})\n', '            summary.update({"strategy_profile_run_mode": self.config.strategy_profile_run_mode, "use_intrabar_data": self.config.use_intrabar_data, "intrabar_csv": str(self.config.intrabar_csv) if self.config.intrabar_csv else None, "strategy_timeframe": self.config.strategy_timeframe_minutes, "intrabar_timeframe": self.config.intrabar_timeframe_minutes, "atr_period": self.config.atr_period, "atr_multiplier": self.config.atr_multiplier})\n')
replace_if_present("crypto_strategy_lab/gui/worker.py", '            if self.config.enable_strategy_profiles and self.config.strategy_profile_run_mode == "BOTH":\n', '            if self.config.strategy_profile_run_mode == "BOTH":\n')
replace_between("crypto_strategy_lab/gui/worker.py", "            if engine.random_entry_active:\n", "            if self.config.save_feature_analysis_reports:\n", "")

# Engine entry pipeline: current profiles + current S/R only. Session VWAP remains
# because VWAP_DISTANCE is a current profile rule; the old breakout entry mode is removed.
replace_if_present("crypto_strategy_lab/engine.py", "from random import Random\n", "")
replace_if_present("crypto_strategy_lab/engine.py", "from crypto_strategy_lab.entry_filters import ADXFilter, BBWidthFilter, DISpreadFilter\n", "")
replace_if_present("crypto_strategy_lab/engine.py", "from crypto_strategy_lab.strategy import custom_entry_signal\n", "")
replace_if_present(
    "crypto_strategy_lab/engine.py",
    '; self.risk=self._risk_array(); self.entry_filters=[ADXFilter(self.config,self.adx_values),BBWidthFilter(self.config,self.bb_width),DISpreadFilter(self.config,self.di_spread)]\n',
    '; self.risk=self._risk_array()\n',
)
replace_if_present("crypto_strategy_lab/engine.py", "        self.pending_vwap_breakout=None\n", "")
replace_if_present("crypto_strategy_lab/engine.py", "        self.skip_monday_tz=ZoneInfo(config.skip_monday_timezone)\n", "")
replace_if_present("crypto_strategy_lab/engine.py", "        self.random_entry_active = bool(config.enable_random_entry and config.entry_timing_mode == EntryTimingMode.RANDOM_AFTER_PAIR_CLOSE)\n        self.random_rng = Random(config.random_seed) if self.random_entry_active else None\n        # A separate stream keeps sizing flips independent from random-entry draws.\n        self.coin_flip_rng = Random(config.coin_flip_seed) if config.enable_coin_flip_sizing else None\n        self.random_entry_decisions=[]; self.random_skips=0; self.last_closed_pair_id=None; self.previous_pair_close_time=None; self.pair_closed_index=None; self.reentry_gates=[]; self.reentry_gate_release_index=None\n", "")
replace_between("crypto_strategy_lab/engine.py", "    def _vwap_breakout_signal(self, i):\n", "    def run(self)->pd.DataFrame:\n", "")
replace_if_present("crypto_strategy_lab/engine.py", "            self._update_reentry_gates(i)\n", "")
replace_if_present("crypto_strategy_lab/engine.py", '    def _execution_time(self,i): return pd.Timestamp(self.times[i]) if (self.config.enable_daily_entry_schedule or self.random_entry_active) else self._entry_time(i)\n', '    def _execution_time(self,i): return pd.Timestamp(self.times[i]) if self.config.enable_daily_entry_schedule else self._entry_time(i)\n')
replace_if_present(
    "crypto_strategy_lab/engine.py",
    '        if active_at_candle_start or len(self.active_pairs) >= self.config.max_active_pairs or self._reentry_gate_blocks(i):\n            self._record_skipped_daily_entry(scheduled_ts, "REENTRY_GATE" if self._reentry_gate_blocks(i) else "ACTIVE_TRADE")\n',
    '        if active_at_candle_start or len(self.active_pairs) >= self.config.max_active_pairs:\n            self._record_skipped_daily_entry(scheduled_ts, "ACTIVE_TRADE")\n',
)
replace_if_present("crypto_strategy_lab/engine.py", '        return i > 0 and not self._reentry_gate_blocks(i) and np.isfinite(self.risk[i-1]) and self.risk[i-1] > 0 and len(self.active_pairs) < self.config.max_active_pairs and self._in_trading_window(i)\n', '        return i > 0 and np.isfinite(self.risk[i-1]) and self.risk[i-1] > 0 and len(self.active_pairs) < self.config.max_active_pairs and self._in_trading_window(i)\n')
replace_between(
    "crypto_strategy_lab/engine.py",
    "    def _entry_decision(self, i, active_at_candle_start=False):\n",
    "    def _should_enter(self,i):\n",
    '''    def _entry_decision(self, i, active_at_candle_start=False):\n        if self.config.enable_daily_entry_schedule:\n            return self._daily_entry_decision(i, active_at_candle_start)\n        return {"execution_index": i, "indicator_index": i, "scheduled_timestamp": None, "actual_entry_timestamp": self._entry_time(i), "entry_schedule_status": None} if self._should_enter(i) else None\n''',
)
replace_between(
    "crypto_strategy_lab/engine.py",
    "    def _should_enter(self,i):\n",
    "    def _entry_filter_result(self, i, execution_i=None):\n",
    '''    def _should_enter(self,i):\n        if not np.isfinite(self.risk[i]) or self.risk[i] <= 0 or len(self.active_pairs) >= self.config.max_active_pairs or not self._in_trading_window(i):\n            return False\n        if self.last_timeout_exit_time is not None and self._entry_time(i) <= self.last_timeout_exit_time:\n            return False\n        if self.config.entry_mode == EntryMode.WAIT_UNTIL_CLOSED:\n            return not self.active_pairs\n        if self.config.entry_mode == EntryMode.EVERY_N_CANDLES:\n            return i % self.config.entry_interval == 0\n        return False\n''',
)
replace_between(
    "crypto_strategy_lab/engine.py",
    "    def _entry_filter_result(self, i, execution_i=None):\n",
    "    def _should_reject_for_sr(self, i, direction, sr_context=None):\n",
    '''    def _entry_filter_result(self, i, execution_i=None):\n        self._pending_sr_context = None\n        profile_result = self._strategy_profile_filter_result(i, execution_i)\n        if not profile_result[0]:\n            return profile_result\n        if self.config.enable_support_resistance_analysis:\n            direction = self._selected_direction(i)\n            sr_reject, sr_reason = self._should_reject_for_sr(i, direction, None)\n            if sr_reject:\n                return False, sr_reason\n        return True, profile_result[1]\n\n''',
)
replace_between("crypto_strategy_lab/engine.py", "    def _adx_filter_result(self, i):\n", "    def _record_skipped_signal(self, i, reason):\n", "")
replace_between(
    "crypto_strategy_lab/engine.py",
    "    def _entry_leg_count(self):\n",
    "    def _active_positions(self, pair):\n",
    '''    def _entry_leg_count(self):\n        return 1\n''',
)

# Audit marker.
audit = ROOT / "tools/stage19_audit_legacy_config.py"
text = audit.read_text(encoding="utf-8")
if '    "strategy_csv",\n' not in text:
    text = text.replace('LEGACY = {\n', 'LEGACY = {\n    "strategy_csv",\n')
    audit.write_text(text, encoding="utf-8")

print("Applied Stage 19 hard-cleanup migration batch.")
