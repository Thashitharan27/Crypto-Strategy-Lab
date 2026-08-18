"""Temporary Stage 19 migration for the last retired production accesses."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "crypto_strategy_lab/engine.py"


def replace_if_present(old: str, new: str) -> None:
    text = ENGINE.read_text(encoding="utf-8")
    if old in text:
        ENGINE.write_text(text.replace(old, new), encoding="utf-8")


def replace_between(start: str, end: str, replacement: str) -> None:
    text = ENGINE.read_text(encoding="utf-8")
    start_i = text.find(start)
    if start_i < 0:
        return
    end_i = text.find(end, start_i)
    if end_i < 0:
        raise SystemExit(f"Stage 19 final cleanup end marker missing: {end!r}")
    ENGINE.write_text(text[:start_i] + replacement + text[end_i:], encoding="utf-8")


replace_if_present(
    "from crypto_strategy_lab.config import BacktestConfig, EntryMode, IntrabarMissingPolicy, PositionSizingMode, RiskMode, TiePolicy, BreakEvenMode, BreakEvenSameCandlePolicy, TradeDirectionMode, DIExecutionMode, DailyEntryMissedPolicy, TrailApplyTo, TrailIntrabarMode, TrailActivationTrigger, AfterTP1StopMode, TP2ExitMode, EntryTimingMode, RandomEntryStartMode, VWAPConfirmationMode\n",
    "from crypto_strategy_lab.config import BacktestConfig, EntryMode, IntrabarMissingPolicy, RiskMode, TiePolicy, DailyEntryMissedPolicy, AfterTP1StopMode\n",
)

# Event-based trailing activation belonged to the retired global trailing mode.
# Current Strategy Profiles activate trailing only at their configured R price.
replace_between(
    "    def _trail_event_matches(self,event):\n",
    "    def _maybe_partial_sl_exit(self,pos,i,high,low,timestamp,source):\n",
    "",
)
# Remove the more deeply indented occurrence first so the shorter whitespace
# prefix cannot leave indentation debris behind.
replace_if_present('                self._activate_trailing_from_event(pos,"SL1",timestamp,pos.sl1_price)\n', "")
replace_if_present('            self._activate_trailing_from_event(pos,"SL1",timestamp,pos.sl1_price)\n', "")
replace_if_present('            self._activate_trailing_from_event(pos,"TP1",timestamp,pos.tp1_price)\n', "")

# The only retained intrabar policy is the existing pessimistic policy: an
# already-active stop is checked before favourable movement; a newly ratcheted
# stop never manufactures a same-bar exit.
replace_if_present(
    "pos.trailing_enabled and pos.trailing_active and self.config.trail_intrabar_mode==TrailIntrabarMode.PESSIMISTIC",
    "pos.trailing_enabled and pos.trailing_active",
)
replace_if_present(
    "pos.trailing_enabled and (self.config.trail_intrabar_mode==TrailIntrabarMode.OPTIMISTIC or not pos.trailing_active)",
    "pos.trailing_enabled and not pos.trailing_active",
)
replace_if_present(
    "pos.is_open and pos.trailing_enabled and (self.config.trail_intrabar_mode==TrailIntrabarMode.OPTIMISTIC or not pos.trailing_active)",
    "pos.is_open and pos.trailing_enabled and not pos.trailing_active",
)
replace_if_present(
    "trailing_prechecked=pos.trailing_enabled and pos.trailing_active and self.config.trail_intrabar_mode==TrailIntrabarMode.PESSIMISTIC",
    "trailing_prechecked=pos.trailing_enabled and pos.trailing_active",
)
replace_between(
    "    def _maybe_trailing_exit(self, pos, i, high, low, timestamp, source):\n",
    "    def _close_at_stop(self,pos,i,raw,reason,source,timestamp):\n",
    '''    def _maybe_trailing_exit(self, pos, i, high, low, timestamp, source):\n        """Apply current Strategy Profile trailing with pessimistic OHLC ordering.\n\n        The stop that existed at bar open has priority. Only after that check can\n        the favourable extreme activate or ratchet the trail. A newly raised stop\n        becomes eligible on the next processed bar, avoiding invented intrabar paths.\n        """\n        is_long = pos.side == Side.LONG\n        old_stop = (\n            max(pos.sl, pos.be_stop_price or -np.inf, pos.trailing_stop or -np.inf)\n            if is_long else\n            min(pos.sl, pos.be_stop_price or np.inf, pos.trailing_stop or np.inf)\n        )\n        stop_hit = low <= old_stop if is_long else high >= old_stop\n        if stop_hit:\n            reason = (\n                ExitReason.TRAILING_STOP\n                if pos.trailing_active and pos.trailing_stop is not None and abs(old_stop-pos.trailing_stop) < 1e-9\n                else (\n                    pos.be_exit_reason\n                    if pos.be_triggered and pos.be_stop_price is not None and abs(old_stop-pos.be_stop_price) < 1e-9\n                    else ExitReason.SL\n                )\n            )\n            return self._close_at_stop(pos, i, old_stop, reason, source, timestamp)\n\n        activation_hit = (\n            (high >= pos.trailing_activation_price if is_long else low <= pos.trailing_activation_price)\n            if pos.trailing_activation_price is not None else False\n        )\n        if not pos.trailing_active and activation_hit:\n            pos.trailing_active = True\n            pos.trailing_activation_time = pd.Timestamp(timestamp)\n        if pos.trailing_active:\n            extreme = high if is_long else low\n            pos.favourable_price = max(pos.favourable_price, extreme) if is_long else min(pos.favourable_price, extreme)\n            distance_r = float(pos.trailing_distance_r)\n            candidate = (\n                pos.favourable_price - pos.risk*distance_r\n                if is_long else\n                pos.favourable_price + pos.risk*distance_r\n            )\n            pos.trailing_stop = (\n                max(pos.trailing_stop or -np.inf, candidate)\n                if is_long else\n                min(pos.trailing_stop or np.inf, candidate)\n            )\n            active_stop = (\n                max(pos.sl, pos.be_stop_price or -np.inf, pos.trailing_stop)\n                if is_long else\n                min(pos.sl, pos.be_stop_price or np.inf, pos.trailing_stop)\n            )\n            pos.sl = active_stop\n            pos.final_active_stop = active_stop\n        return False\n\n''',
)

# Single-side execution no longer has a global direction sorting/schema mode.
replace_between(
    "        if not frame.empty and self.config.trade_direction == TradeDirectionMode.BOTH_INDEPENDENT:\n",
    "        if not frame.empty:\n",
    "",
)
replace_if_present('        frame.attrs["random_entry_decisions"] = list(self.random_entry_decisions)\n', "")
replace_between(
    "    def telemetry_frame(self):\n",
    "    def _num(self, arr, i):\n",
    '''    def telemetry_frame(self):\n        from crypto_strategy_lab.telemetry import TELEMETRY_COLUMNS\n        return pd.DataFrame(self.telemetry_rows, columns=TELEMETRY_COLUMNS)\n\n''',
)
replace_if_present(
    '''        if self.config.trade_direction == TradeDirectionMode.LONG_ONLY:\n            row={k:v for k,v in row.items() if not k.startswith("short_")}\n        elif self.config.trade_direction == TradeDirectionMode.SHORT_ONLY:\n            row={k:v for k,v in row.items() if not k.startswith("long_")}\n''',
    "",
)
replace_if_present(
    '"long_tp":(np.nan if pair.long is not None and pair.long.r_step_trailing_enabled and pos.r_step_maximum_r==0 else (pair.long.tp if pair.long is not None else np.nan))',
    '"long_tp":(np.nan if pair.long is not None and pair.long.r_step_trailing_enabled and pair.long.r_step_maximum_r==0 else (pair.long.tp if pair.long is not None else np.nan))',
)

print("Removed the final retired engine config accesses and fixed single-side telemetry.")
