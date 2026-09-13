from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Core configuration contract: explicit, backwards-compatible entry timing.
# ---------------------------------------------------------------------------
replace_once(
    "crypto_strategy_lab/config.py",
    'class EntryMode(str, Enum):\n    WAIT_UNTIL_CLOSED = "WAIT_UNTIL_CLOSED"; EVERY_N_CANDLES = "EVERY_N_CANDLES"\n',
    'class EntryMode(str, Enum):\n    WAIT_UNTIL_CLOSED = "WAIT_UNTIL_CLOSED"; EVERY_N_CANDLES = "EVERY_N_CANDLES"\n'
    'class EntryTimingMode(str, Enum):\n'
    '    SIGNAL_CLOSE = "SIGNAL_CLOSE"; NEXT_CANDLE_OPEN = "NEXT_CANDLE_OPEN"\n',
)
replace_once(
    "crypto_strategy_lab/config.py",
    '    entry_mode: EntryMode = EntryMode.WAIT_UNTIL_CLOSED\n    entry_interval: int = 1\n',
    '    entry_mode: EntryMode = EntryMode.WAIT_UNTIL_CLOSED\n'
    '    entry_timing_mode: EntryTimingMode = EntryTimingMode.SIGNAL_CLOSE\n'
    '    entry_interval: int = 1\n',
)
replace_once(
    "crypto_strategy_lab/config.py",
    '        if isinstance(self.entry_mode, str):\n            object.__setattr__(self, "entry_mode", EntryMode(self.entry_mode))\n',
    '        if isinstance(self.entry_mode, str):\n            object.__setattr__(self, "entry_mode", EntryMode(self.entry_mode))\n'
    '        if isinstance(self.entry_timing_mode, str):\n'
    '            object.__setattr__(self, "entry_timing_mode", EntryTimingMode(self.entry_timing_mode))\n',
)

# Flat GUI compatibility contract keeps old saved configs on signal-close fills.
replace_once(
    "crypto_strategy_lab/gui/config_logic.py",
    '    EntryMode,\n    IntrabarMissingPolicy,',
    '    EntryMode,\n    EntryTimingMode,\n    IntrabarMissingPolicy,',
)
replace_once(
    "crypto_strategy_lab/gui/config_logic.py",
    '    "entry_mode": "WAIT_UNTIL_CLOSED",\n    "entry_interval": 1,',
    '    "entry_mode": "WAIT_UNTIL_CLOSED",\n'
    '    "entry_timing_mode": "SIGNAL_CLOSE",\n'
    '    "entry_interval": 1,',
)
replace_once(
    "crypto_strategy_lab/gui/config_logic.py",
    '    if values["entry_mode"] not in (EntryMode.WAIT_UNTIL_CLOSED.value, EntryMode.EVERY_N_CANDLES.value):\n        errors.append("Invalid entry mode.")\n',
    '    if values["entry_mode"] not in (EntryMode.WAIT_UNTIL_CLOSED.value, EntryMode.EVERY_N_CANDLES.value):\n'
    '        errors.append("Invalid entry mode.")\n'
    '    if values["entry_timing_mode"] not in (EntryTimingMode.SIGNAL_CLOSE.value, EntryTimingMode.NEXT_CANDLE_OPEN.value):\n'
    '        errors.append("Invalid entry timing mode.")\n',
)
replace_once(
    "crypto_strategy_lab/gui/config_logic.py",
    '        entry_mode=EntryMode(merged["entry_mode"]),\n        entry_interval=int(merged["entry_interval"]),',
    '        entry_mode=EntryMode(merged["entry_mode"]),\n'
    '        entry_timing_mode=EntryTimingMode(merged["entry_timing_mode"]),\n'
    '        entry_interval=int(merged["entry_interval"]),',
)

# Native composed Data Lake config owns the same execution choice.
replace_once(
    "crypto_strategy_lab/data_lake_config.py",
    'class ExecutionConfig:\n    profiles: Mapping[str, ExecutionProfileConfig] = field(default_factory=_execution_profiles)\n    initial_equity: float = 1000.0\n',
    'class ExecutionConfig:\n'
    '    profiles: Mapping[str, ExecutionProfileConfig] = field(default_factory=_execution_profiles)\n'
    '    entry_timing_mode: str = "SIGNAL_CLOSE"\n'
    '    initial_equity: float = 1000.0\n',
)
replace_once(
    "crypto_strategy_lab/data_lake_config.py",
    '        if execution.initial_equity <= 0 or execution.fixed_r <= 0 or execution.percent_r <= 0:\n            raise ValueError("execution equity/risk settings must be positive")\n',
    '        if execution.entry_timing_mode not in {"SIGNAL_CLOSE", "NEXT_CANDLE_OPEN"}:\n'
    '            raise ValueError("invalid entry timing mode")\n'
    '        if execution.initial_equity <= 0 or execution.fixed_r <= 0 or execution.percent_r <= 0:\n'
    '            raise ValueError("execution equity/risk settings must be positive")\n',
)

# GUI: expose Entry Fill Timing as a normal execution control.
replace_once(
    "crypto_strategy_lab/gui/v2_main_window.py",
    'EXECUTION_GROUPS = (\n    ("Risk", (',
    'EXECUTION_GROUPS = (\n'
    '    ("Entry Fill", ("entry_timing_mode",), None),\n'
    '    ("Risk", (',
)
replace_once(
    "crypto_strategy_lab/gui/v2_main_window.py",
    '        "entry_mode": ("WAIT_UNTIL_CLOSED", "EVERY_N_CANDLES"),\n',
    '        "entry_mode": ("WAIT_UNTIL_CLOSED", "EVERY_N_CANDLES"),\n'
    '        "entry_timing_mode": ("SIGNAL_CLOSE", "NEXT_CANDLE_OPEN"),\n',
)
replace_once(
    "crypto_strategy_lab/gui/ux_presentation.py",
    '    "strategy_profile_run_mode": FieldPresentation("Profile Test Mode"),\n',
    '    "strategy_profile_run_mode": FieldPresentation("Profile Test Mode"),\n'
    '    "entry_timing_mode": FieldPresentation(\n'
    '        "Entry Fill Timing",\n'
    '        "Signal Close preserves historical fills. Next Candle Open queues a completed signal and fills at the next strategy candle open before that candle is processed.",\n'
    '    ),\n',
)
replace_once(
    "crypto_strategy_lab/gui/ux_presentation.py",
    'ENUM_LABELS = {\n',
    'ENUM_LABELS = {\n'
    '    "entry_timing_mode": {\n'
    '        "SIGNAL_CLOSE": "Signal Candle Close — Legacy",\n'
    '        "NEXT_CANDLE_OPEN": "Next Candle Open — Causal",\n'
    '    },\n',
)

# User selection defaults: EMA 9/20 -> next-open, other signal strategies -> legacy.
# Programmatic config loading uses setCurrentIndex and does NOT emit QComboBox.activated,
# preserving historical saved configs that do not contain the new field.
replace_once(
    "crypto_strategy_lab/gui/rule_main_window.py",
    '        self.base_execution_form.changed.connect(self._refresh_summary_from_widgets)\n        self.apply_config(self.config)\n',
    '        self.base_execution_form.changed.connect(self._refresh_summary_from_widgets)\n'
    '        self.apply_config(self.config)\n'
    '        self.rule_builder.direction_mode.activated.connect(\n'
    '            self._apply_signal_strategy_entry_timing_default\n'
    '        )\n',
)
replace_once(
    "crypto_strategy_lab/gui/rule_main_window.py",
    '    def _capture_run_snapshot(self):\n',
    '    def _apply_signal_strategy_entry_timing_default(self, *_args) -> None:\n'
    '        """Apply a researcher-facing default only on an explicit strategy selection."""\n'
    '        timing = self.execution_form.widgets.get("entry_timing_mode")\n'
    '        if timing is None or not hasattr(timing, "findData"):\n'
    '            return\n'
    '        strategy = self.rule_builder.direction_mode.currentData()\n'
    '        target = "NEXT_CANDLE_OPEN" if strategy == "EMA_9_20_PULLBACK" else "SIGNAL_CLOSE"\n'
    '        index = timing.findData(target)\n'
    '        if index >= 0:\n'
    '            timing.setCurrentIndex(index)\n\n'
    '    def _capture_run_snapshot(self):\n',
)

# ---------------------------------------------------------------------------
# Simulator: defer causal next-open fills and execute before processing that bar.
# ---------------------------------------------------------------------------
replace_once(
    "crypto_strategy_lab/engine.py",
    'self.daily_entries_next_available=0; self.pending_daily_entry=None; self.next_pair_id=1;',
    'self.daily_entries_next_available=0; self.pending_daily_entry=None; self.pending_next_open_entry=None; self.next_pair_id=1;',
)
replace_once(
    "crypto_strategy_lab/data_lake_production_engine.py",
    'self.signals_evaluated=0; self.daily_entry_opportunities=0; self.daily_entries_on_schedule=0; self.daily_entries_next_available=0; self.pending_daily_entry=None; self.next_pair_id=1',
    'self.signals_evaluated=0; self.daily_entry_opportunities=0; self.daily_entries_on_schedule=0; self.daily_entries_next_available=0; self.pending_daily_entry=None; self.pending_next_open_entry=None; self.next_pair_id=1',
)
replace_once(
    "crypto_strategy_lab/engine.py",
    '    def _entry_decision(self, i, active_at_candle_start=False):\n        if self.config.enable_daily_entry_schedule:\n            return self._daily_entry_decision(i, active_at_candle_start)\n        return {"execution_index": i, "indicator_index": i, "scheduled_timestamp": None, "actual_entry_timestamp": self._entry_time(i), "entry_schedule_status": None} if self._should_enter(i) else None\n',
    '''    def _entry_timing_mode(self):\n        raw = getattr(self.config, "entry_timing_mode", "SIGNAL_CLOSE")\n        return str(getattr(raw, "value", raw)).upper()\n\n    def _entry_decision(self, i, active_at_candle_start=False):\n        if self.config.enable_daily_entry_schedule:\n            return self._daily_entry_decision(i, active_at_candle_start)\n        if self._entry_timing_mode() == "NEXT_CANDLE_OPEN":\n            if i + 1 >= len(self.times) or not self._should_enter(i):\n                return None\n            return {\n                "execution_index": i + 1,\n                "indicator_index": i,\n                "scheduled_timestamp": pd.Timestamp(self.times[i + 1]),\n                "actual_entry_timestamp": None,\n                "entry_schedule_status": "NEXT_CANDLE_OPEN",\n                "fill_price_source": "NEXT_CANDLE_OPEN",\n                "defer_to_next_open": True,\n            }\n        return {\n            "execution_index": i,\n            "indicator_index": i,\n            "scheduled_timestamp": None,\n            "actual_entry_timestamp": self._entry_time(i),\n            "entry_schedule_status": None,\n            "fill_price_source": "SIGNAL_CLOSE",\n        } if self._should_enter(i) else None\n\n    def _execute_pending_next_open_entry(self, i, active_at_candle_start=False):\n        decision = self.pending_next_open_entry\n        if not decision or int(decision.get("execution_index", -1)) != i:\n            return\n        self.pending_next_open_entry = None\n        indicator_i = int(decision["indicator_index"])\n        decision["actual_entry_timestamp"] = pd.Timestamp(self.times[i])\n        if active_at_candle_start or len(self.active_pairs) >= self.config.max_active_pairs:\n            self._record_skipped_signal(indicator_i, "NEXT_OPEN_ACTIVE_TRADE")\n            return\n        passed, reason = self._entry_filter_result(indicator_i, i)\n        if passed:\n            self._open_pair(i, passed, reason, decision)\n        else:\n            self._record_skipped_signal(indicator_i, reason)\n''',
)
replace_once(
    "crypto_strategy_lab/engine.py",
    '''    def run(self)->pd.DataFrame:\n        total=len(self.times)\n        self._emit_progress(0,total)\n        for i in range(total):\n            self.current_index=i\n            active_at_candle_start = bool(self.active_pairs)\n            self._update_positions_to_strategy_index(i); self._record_active_telemetry(i); self._collect_closed_pairs()\n            decision = self._entry_decision(i, active_at_candle_start)\n            if decision:\n                self.signals_evaluated += 1\n                passed, reason = self._entry_filter_result(decision["indicator_index"], decision["execution_index"])\n                if passed: self._open_pair(decision["execution_index"], passed, reason, decision)\n                else:\n                    self._record_skipped_signal(decision["indicator_index"], reason)\n                    if self.config.enable_daily_entry_schedule: self._record_skipped_daily_entry(decision["scheduled_timestamp"], "FILTER_REJECTED", reason)\n            processed=i+1\n            if processed == total or processed % self.progress_interval == 0:\n                self._emit_progress(processed,total)\n        self._force_close_end(); self._collect_closed_pairs(force=True); self._emit_progress(total,total); return self.results_frame()\n''',
    '''    def run(self)->pd.DataFrame:\n        total=len(self.times)\n        self._emit_progress(0,total)\n        for i in range(total):\n            self.current_index=i\n            active_at_candle_start = bool(self.active_pairs)\n            # A queued next-open order becomes live at this candle's open, before\n            # any intrabar/high-low processing for the execution candle.\n            self._execute_pending_next_open_entry(i, active_at_candle_start)\n            self._update_positions_to_strategy_index(i); self._record_active_telemetry(i); self._collect_closed_pairs()\n            decision = self._entry_decision(i, active_at_candle_start)\n            if decision:\n                self.signals_evaluated += 1\n                if decision.get("defer_to_next_open"):\n                    self.pending_next_open_entry = decision\n                else:\n                    passed, reason = self._entry_filter_result(decision["indicator_index"], decision["execution_index"])\n                    if passed: self._open_pair(decision["execution_index"], passed, reason, decision)\n                    else:\n                        self._record_skipped_signal(decision["indicator_index"], reason)\n                        if self.config.enable_daily_entry_schedule: self._record_skipped_daily_entry(decision["scheduled_timestamp"], "FILTER_REJECTED", reason)\n            processed=i+1\n            if processed == total or processed % self.progress_interval == 0:\n                self._emit_progress(processed,total)\n        self._force_close_end(); self._collect_closed_pairs(force=True); self._emit_progress(total,total); return self.results_frame()\n''',
)

# Base fill logic: use the queued execution candle open and its true timestamp.
replace_once(
    "crypto_strategy_lab/engine.py",
    '        ind_i = schedule["indicator_index"] if schedule else i\n        raw = self.open[i] if self.config.enable_daily_entry_schedule else self.close[i]\n',
    '        ind_i = schedule["indicator_index"] if schedule else i\n'
    '        fill_source = str((schedule or {}).get("fill_price_source", "")).upper()\n'
    '        open_fill = self.config.enable_daily_entry_schedule or fill_source == "NEXT_CANDLE_OPEN"\n'
    '        raw = self.open[i] if open_fill else self.close[i]\n'
    '        entry_timestamp = (schedule or {}).get("actual_entry_timestamp")\n'
    '        if entry_timestamp is None:\n'
    '            entry_timestamp = pd.Timestamp(self.times[i]) if open_fill else self._execution_time(i)\n'
    '        entry_timestamp = pd.Timestamp(entry_timestamp)\n',
)
replace_once(
    "crypto_strategy_lab/engine.py",
    '            side, self._execution_time(i), i, entry, stop, sl, tp, qty, risk_amt, entry * qty,\n',
    '            side, entry_timestamp, i, entry, stop, sl, tp, qty, risk_amt, entry * qty,\n',
)
replace_once(
    "crypto_strategy_lab/engine.py",
    '        pair = TradePair(\n            self.next_pair_id, long, short, self.current_equity, pd.Timestamp(self.times[i]),\n            self._execution_time(i), raw, capped\n        )\n',
    '''        pair_candle_time = (\n            pd.Timestamp(self.times[ind_i])\n            if fill_source == "NEXT_CANDLE_OPEN"\n            else pd.Timestamp(self.times[i])\n        )\n        pair = TradePair(\n            self.next_pair_id, long, short, self.current_equity, pair_candle_time,\n            entry_timestamp, raw, capped\n        )\n''',
)
replace_once(
    "crypto_strategy_lab/engine.py",
    '        pair.trade_direction = direction\n        pair.signal_strategy_mode = getattr(self,"signal_strategy_mode","DI")\n',
    '''        pair.trade_direction = direction\n        pair.signal_strategy_mode = getattr(self,"signal_strategy_mode","DI")\n        pair.entry_timing_mode = (\n            "NEXT_CANDLE_OPEN" if fill_source == "NEXT_CANDLE_OPEN"\n            else "SCHEDULED_CANDLE_OPEN" if self.config.enable_daily_entry_schedule\n            else "SIGNAL_CLOSE"\n        )\n        pair.signal_candle_time = pd.Timestamp(self.times[ind_i])\n        pair.signal_available_at = pd.Timestamp(self.times[ind_i]) + self.entry_delta\n        pair.signal_close_price = float(self.close[ind_i])\n        pair.next_bar_open_price = float(self.open[i]) if fill_source == "NEXT_CANDLE_OPEN" else np.nan\n        if fill_source == "NEXT_CANDLE_OPEN" and pair.signal_close_price:\n            gap = float(self.open[i]) - pair.signal_close_price\n            pair.entry_gap_pct = gap / pair.signal_close_price\n            atr_for_gap = float(self.atr_values[ind_i])\n            pair.entry_gap_atr = gap / atr_for_gap if np.isfinite(atr_for_gap) and atr_for_gap > 0 else np.nan\n        else:\n            pair.entry_gap_pct = 0.0\n            pair.entry_gap_atr = 0.0\n''',
)
replace_once(
    "crypto_strategy_lab/engine.py",
    '            "signal_strategy": getattr(p, "signal_strategy_mode", "DI"),\n',
    '            "signal_strategy": getattr(p, "signal_strategy_mode", "DI"),\n'
    '            "entry_timing_mode": getattr(p, "entry_timing_mode", "SIGNAL_CLOSE"),\n'
    '            "signal_candle_time": getattr(p, "signal_candle_time", p.strategy_candle_open_time),\n'
    '            "signal_available_at": getattr(p, "signal_available_at", p.strategy_entry_time),\n'
    '            "signal_close_price": getattr(p, "signal_close_price", np.nan),\n'
    '            "next_bar_open_price": getattr(p, "next_bar_open_price", np.nan),\n'
    '            "entry_gap_pct": getattr(p, "entry_gap_pct", 0.0),\n'
    '            "entry_gap_atr": getattr(p, "entry_gap_atr", 0.0),\n',
)
replace_once(
    "crypto_strategy_lab/engine.py",
    '            "entry_price": primary.entry_price,\n',
    '            "entry_price": primary.entry_price,\n            "actual_entry_price": primary.entry_price,\n',
)

# Structural entry calculations now use execution open whenever execution follows signal.
replace_once(
    "crypto_strategy_lab/sr_dynamic_tp_engine.py",
    '        if self.config.enable_daily_entry_schedule and execution_i is not None:\n            raw = float(self.open[execution_i])\n        else:\n            raw = float(self.close[indicator_i])\n',
    '        if execution_i is not None and execution_i > indicator_i:\n'
    '            raw = float(self.open[execution_i])\n'
    '        elif self.config.enable_daily_entry_schedule and execution_i is not None:\n'
    '            raw = float(self.open[execution_i])\n'
    '        else:\n'
    '            raw = float(self.close[indicator_i])\n',
)

# EMA micro-swing geometry: explicitly reject a next-open gap through the stop.
replace_once(
    "crypto_strategy_lab/ema_pullback.py",
    '        stop_price = level - buffer_price if direction == "LONG" else level + buffer_price\n        distance = entry - stop_price if direction == "LONG" else stop_price - entry\n',
    '''        stop_price = level - buffer_price if direction == "LONG" else level + buffer_price\n        if execution_i is not None and execution_i > i:\n            raw_open = float(self.open[execution_i])\n            gap_through = raw_open <= stop_price if direction == "LONG" else raw_open >= stop_price\n            if gap_through:\n                return {\n                    "passed": False, "applied": False,\n                    "reason": "ENTRY_INVALIDATED_GAP_THROUGH_STOP",\n                    "distance": None, "level_price": level, "boundary_price": level,\n                    "stop_price": stop_price,\n                    "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),\n                    "micro_swing_index": swing_i, "micro_swing": True,\n                }\n        distance = entry - stop_price if direction == "LONG" else stop_price - entry\n''',
)
replace_once(
    "crypto_strategy_lab/ema_pullback.py",
    '    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):\n',
    '''    def _build_result_row(self, p, row_kind, positions):\n        row = super()._build_result_row(p, row_kind, positions)\n        pos = positions[0] if positions else None\n        row["micro_swing_stop_applied"] = bool(getattr(pos, "micro_swing_stop_applied", False)) if pos is not None else False\n        row["micro_swing_index"] = getattr(pos, "micro_swing_index", None) if pos is not None else None\n        row["micro_swing_level_price"] = getattr(pos, "micro_swing_level_price", np.nan) if pos is not None else np.nan\n        row["micro_swing_stop_price"] = getattr(pos, "micro_swing_stop_price", np.nan) if pos is not None else np.nan\n        row["micro_swing_stop_distance_atr"] = getattr(pos, "micro_swing_stop_distance_atr", np.nan) if pos is not None else np.nan\n        return row\n\n    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):\n''',
)

# ---------------------------------------------------------------------------
# Focused regression/causality tests.
# ---------------------------------------------------------------------------
write(
    "tests/test_next_candle_open_entry.py",
    '''from __future__ import annotations\n\nfrom types import SimpleNamespace\n\nimport numpy as np\nimport pandas as pd\n\nfrom crypto_strategy_lab.config import BacktestConfig, EntryTimingMode\nfrom crypto_strategy_lab.data_lake_config import ExecutionConfig, ResearchRunConfig\nfrom crypto_strategy_lab.engine import BacktestEngine\nfrom crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine\nfrom crypto_strategy_lab.sr_dynamic_tp_engine import SRDynamicTPBacktestEngine\n\n\ndef test_entry_timing_defaults_preserve_historical_signal_close():\n    assert BacktestConfig().entry_timing_mode == EntryTimingMode.SIGNAL_CLOSE\n    assert ExecutionConfig().entry_timing_mode == "SIGNAL_CLOSE"\n    config = ResearchRunConfig(execution=ExecutionConfig(entry_timing_mode="NEXT_CANDLE_OPEN"))\n    config.validate()\n\n\ndef test_next_open_decision_defers_one_strategy_candle_without_reading_price():\n    engine = object.__new__(BacktestEngine)\n    engine.config = SimpleNamespace(enable_daily_entry_schedule=False, entry_timing_mode="NEXT_CANDLE_OPEN")\n    engine.times = np.array([\n        np.datetime64("2026-01-01T00:00"),\n        np.datetime64("2026-01-01T00:05"),\n        np.datetime64("2026-01-01T00:10"),\n    ])\n    engine._should_enter = lambda i: i == 1\n    decision = BacktestEngine._entry_decision(engine, 1, False)\n    assert decision["indicator_index"] == 1\n    assert decision["execution_index"] == 2\n    assert decision["defer_to_next_open"] is True\n    assert decision["actual_entry_timestamp"] is None\n    assert decision["fill_price_source"] == "NEXT_CANDLE_OPEN"\n\n\ndef test_structural_geometry_uses_execution_candle_open_for_deferred_entry():\n    engine = object.__new__(SRDynamicTPBacktestEngine)\n    engine.config = SimpleNamespace(enable_daily_entry_schedule=False, slippage=0.001)\n    engine.close = np.array([100.0, 101.0])\n    engine.open = np.array([99.0, 110.0])\n    assert engine._expected_entry_price(0, 1, "LONG") == 110.0 * 1.001\n    assert engine._expected_entry_price(0, 1, "SHORT") == 110.0 * 0.999\n\n\ndef test_ema_next_open_gap_through_micro_swing_stop_is_rejected_explicitly():\n    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)\n    engine.config = SimpleNamespace(strategy_timeframe_minutes=5, slippage=0.0, enable_daily_entry_schedule=False)\n    engine.open = np.full(12, 110.0)\n    engine.open[11] = 98.0\n    engine.close = np.full(12, 110.0)\n    engine.high = np.full(12, 111.0)\n    engine.low = np.full(12, 109.0)\n    engine.atr_values = np.full(12, 2.0)\n    engine._effective_trade_direction = lambda _i: "LONG"\n    engine._latest_confirmed_micro_swing = lambda _i, _direction: (7, 100.0)\n    plan = engine._ema_920_micro_swing_stop_plan(10, 11)\n    assert plan["passed"] is False\n    assert plan["reason"] == "ENTRY_INVALIDATED_GAP_THROUGH_STOP"\n    assert plan["stop_price"] == 99.9\n\n\ndef test_queued_next_open_entry_is_opened_before_execution_candle_is_processed():\n    events = []\n\n    class Probe(BacktestEngine):\n        def __init__(self):\n            self.config = SimpleNamespace(\n                enable_daily_entry_schedule=False,\n                entry_timing_mode="NEXT_CANDLE_OPEN",\n                max_active_pairs=1,\n            )\n            self.times = np.array([\n                np.datetime64("2026-01-01T00:00"),\n                np.datetime64("2026-01-01T00:05"),\n            ])\n            self.active_pairs = []\n            self.completed_pairs = []\n            self.pending_next_open_entry = None\n            self.signals_evaluated = 0\n            self.progress_interval = 50\n            self.next_pair_id = 1\n\n        def _should_enter(self, i):\n            return i == 0\n\n        def _entry_filter_result(self, indicator_i, execution_i=None):\n            events.append(("filter", indicator_i, execution_i))\n            return True, "passed"\n\n        def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="", schedule=None):\n            events.append(("open", i, schedule["indicator_index"]))\n            self.active_pairs.append(object())\n\n        def _update_positions_to_strategy_index(self, i):\n            events.append(("update", i, bool(self.active_pairs)))\n\n        def _record_active_telemetry(self, _i):\n            return None\n\n        def _collect_closed_pairs(self, force=False):\n            return None\n\n        def _record_skipped_signal(self, i, reason):\n            events.append(("skip", i, reason))\n\n        def _force_close_end(self):\n            return None\n\n        def _emit_progress(self, *_args):\n            return None\n\n        def results_frame(self):\n            return pd.DataFrame()\n\n    Probe().run()\n    open_position = events.index(("open", 1, 0))\n    process_execution_candle = events.index(("update", 1, True))\n    assert open_position < process_execution_candle\n\n\ndef test_rule_gui_user_selection_applies_ema_next_open_default_without_forcing_loaded_configs(monkeypatch):\n    import os\n    import pytest\n\n    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")\n    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)\n    from crypto_strategy_lab.gui.rule_main_window import MainWindow\n\n    app = widgets.QApplication.instance() or widgets.QApplication([])\n\n    class Catalog:\n        def symbols(self): return ["BTCUSDT"]\n        def coverage(self, _request): return []\n\n    class Service:\n        catalog = Catalog()\n        def refresh_catalog(self): return 0\n\n    window = MainWindow(service=Service())\n    try:\n        timing = window.execution_form.widgets["entry_timing_mode"]\n        selector = window.rule_builder.direction_mode\n        assert timing.currentData() == "SIGNAL_CLOSE"\n\n        ema_index = selector.findData("EMA_9_20_PULLBACK")\n        selector.setCurrentIndex(ema_index)\n        # Programmatic selection models config loading: no user-activation default.\n        assert timing.currentData() == "SIGNAL_CLOSE"\n        selector.activated.emit(ema_index)\n        assert timing.currentData() == "NEXT_CANDLE_OPEN"\n\n        di_index = selector.findData("DI")\n        selector.setCurrentIndex(di_index)\n        selector.activated.emit(di_index)\n        assert timing.currentData() == "SIGNAL_CLOSE"\n    finally:\n        window.close()\n        _ = app\n''',
)

print("next-candle-open patch applied")
