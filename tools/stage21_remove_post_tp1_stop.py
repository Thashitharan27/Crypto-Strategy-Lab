"""Temporary Stage 21 migration: remove duplicate post-TP1 stop controls."""
from pathlib import Path


def read(path):
    return Path(path).read_text(encoding="utf-8")


def write(path, text):
    Path(path).write_text(text, encoding="utf-8")


def must_replace(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Stage 21 expected block missing: {label}")
    return text.replace(old, new, 1)


def replace_between(text, start, end, new_block, label):
    a = text.find(start)
    if a < 0:
        raise RuntimeError(f"Stage 21 start marker missing: {label}")
    b = text.find(end, a)
    if b < 0:
        raise RuntimeError(f"Stage 21 end marker missing: {label}")
    return text[:a] + new_block + text[b:]


# 1) Strategy Profile schema: delete the duplicate post-TP1 stop contract.
path = "crypto_strategy_lab/strategy_profiles.py"
text = read(path)
text = must_replace(
    text,
    '    after_tp1_stop_mode: str = "KEEP_ORIGINAL_SL"\n    after_tp1_stop_offset_r: float = 0.0\n',
    "",
    "StrategyProfile post-TP1 fields",
)
text = must_replace(
    text,
    '        if self.after_tp1_stop_mode not in ("KEEP_ORIGINAL_SL", "MOVE_TO_ENTRY", "MOVE_TO_R_OFFSET"):\n'
    '            raise ValueError(f"{key}: invalid post-TP1 stop mode")\n'
    '        if self.after_tp1_stop_offset_r < 0:\n'
    '            raise ValueError(f"{key}: post-TP1 stop offset cannot be negative")\n',
    "",
    "StrategyProfile post-TP1 validation",
)
write(path, text)


# 2) Config enum no longer exists.
path = "crypto_strategy_lab/config.py"
text = read(path)
text = must_replace(
    text,
    'class AfterTP1StopMode(str, Enum):\n'
    '    KEEP_ORIGINAL_SL = "KEEP_ORIGINAL_SL"; MOVE_TO_ENTRY = "MOVE_TO_ENTRY"; MOVE_TO_R_OFFSET = "MOVE_TO_R_OFFSET"\n',
    "",
    "AfterTP1StopMode enum",
)
write(path, text)


# 3) Trade state no longer carries post-TP1 compatibility state.
path = "crypto_strategy_lab/trade.py"
text = read(path)
text = must_replace(
    text,
    '    after_tp1_stop_mode: str = "KEEP_ORIGINAL_SL"; after_tp1_stop_offset_r: float = 0.0\n',
    "",
    "Position post-TP1 fields",
)
text = must_replace(
    text,
    '    partial_sl_enabled: bool = False; partial_sl_overridden_after_tp1: bool = False; sl1_price: Optional[float] = None; sl2_price: Optional[float] = None; sl1_quantity: float = 0.0; sl1_hit: bool = False\n',
    '    partial_sl_enabled: bool = False; sl1_price: Optional[float] = None; sl2_price: Optional[float] = None; sl1_quantity: float = 0.0; sl1_hit: bool = False\n',
    "Position partial-SL override flag",
)
write(path, text)


# 4) GUI: Partial Take Profit owns only targets/quantity. Protection owns stop movement.
path = "crypto_strategy_lab/gui/profile_editor.py"
text = read(path)
text = must_replace(
    text,
    '        self._choice("after_tp1_stop_mode",(("Keep original stop","KEEP_ORIGINAL_SL"),("Move stop to entry","MOVE_TO_ENTRY"),("Lock profit at R offset","MOVE_TO_R_OFFSET")))\n'
    '        self._number("after_tp1_stop_offset_r",0,0,1000)\n',
    "",
    "profile editor post-TP1 widgets",
)
text = must_replace(
    text,
    '        for key,label in (("tp1_r","First profit target"),("tp1_close_pct","Position closed at first target"),("tp2_r","Final profit target"),("after_tp1_stop_mode","Remaining stop after first target"),("after_tp1_stop_offset_r","Profit locked after first target")):\n'
    '            self.form.labelForField(self.controls[key]).setText(label)\n'
    '        for key in ("tp1_r","tp2_r","after_tp1_stop_offset_r"):\n',
    '        for key,label in (("tp1_r","First profit target"),("tp1_close_pct","Position closed at first target"),("tp2_r","Final profit target")):\n'
    '            self.form.labelForField(self.controls[key]).setText(label)\n'
    '        for key in ("tp1_r","tp2_r"):\n',
    "profile editor profit labels",
)
text = must_replace(
    text,
    '        self.controls["after_tp1_stop_mode"].currentTextChanged.connect(self._update_management_controls)\n',
    "",
    "profile editor post-TP1 signal",
)
text = must_replace(
    text,
    '        partial_profit=self.controls["partial_profit_enabled"].isChecked()\n'
    '        for key in ("tp1_r","tp1_close_pct","tp2_r","after_tp1_stop_mode"):\n'
    '            self._show_control(key,partial_profit)\n'
    '        self._show_control("after_tp1_stop_offset_r",partial_profit and self.controls["after_tp1_stop_mode"].currentData()=="MOVE_TO_R_OFFSET")\n'
    '        self.controls["reward_risk_ratio"].setEnabled(not partial_profit)\n',
    '        partial_profit=self.controls["partial_profit_enabled"].isChecked()\n'
    '        for key in ("tp1_r","tp1_close_pct","tp2_r"):\n'
    '            self._show_control(key,partial_profit)\n'
    '        self.controls["reward_risk_ratio"].setEnabled(not partial_profit)\n',
    "profile editor partial-profit visibility",
)
write(path, text)


# 5) Engine: remove duplicate contract and make Break-even apply to every current exit path.
path = "crypto_strategy_lab/engine.py"
text = read(path)
text = must_replace(
    text,
    'from crypto_strategy_lab.config import BacktestConfig, EntryMode, IntrabarMissingPolicy, RiskMode, TiePolicy, DailyEntryMissedPolicy, AfterTP1StopMode\n',
    'from crypto_strategy_lab.config import BacktestConfig, EntryMode, IntrabarMissingPolicy, RiskMode, TiePolicy, DailyEntryMissedPolicy\n',
    "engine AfterTP1StopMode import",
)
text = must_replace(
    text,
    '        after_tp1_stop_mode = active_profile.after_tp1_stop_mode\n        after_tp1_stop_offset_r = active_profile.after_tp1_stop_offset_r\n',
    "",
    "engine profile post-TP1 assignment",
)
text = must_replace(
    text,
    '        pos.after_tp1_stop_mode = after_tp1_stop_mode\n        pos.after_tp1_stop_offset_r = after_tp1_stop_offset_r\n',
    "",
    "engine position post-TP1 assignment",
)
text = must_replace(
    text,
    '        pair.applied_after_tp1_stop_mode = after_tp1_stop_mode\n        pair.applied_after_tp1_stop_offset_r = after_tp1_stop_offset_r\n',
    "",
    "engine pair post-TP1 audit",
)

new_exit_bar = '''    def _maybe_exit_bar(self,pos,i,high,low,timestamp,source):
        # Break-even is a Protection rule, independent of the selected profit
        # taking method. A newly raised BE stop is deliberately not eligible
        # until the next processed bar/intrabar candle, avoiding invented OHLC
        # paths inside the candle that triggered it.
        if pos.r_step_trailing_enabled:
            changed=self._maybe_r_step_trailing_exit(pos,i,float(high),float(low),timestamp,source)
            if pos.is_open: self._maybe_activate_break_even(pos,float(high),float(low),timestamp)
            return changed
        if pos.partial_sl_enabled and pos.partial_tp_enabled:
            changed=self._maybe_combined_partial_exit(pos,i,float(high),float(low),timestamp,source)
            if pos.is_open: self._maybe_activate_break_even(pos,float(high),float(low),timestamp)
            return changed
        if pos.partial_sl_enabled:
            changed=self._maybe_partial_sl_exit(pos,i,float(high),float(low),timestamp,source)
            if pos.is_open: self._maybe_activate_break_even(pos,float(high),float(low),timestamp)
            return changed
        if pos.partial_tp_enabled:
            changed=self._maybe_partial_exit(pos,i,float(high),float(low),timestamp,source)
            if pos.is_open: self._maybe_activate_break_even(pos,float(high),float(low),timestamp)
            return changed
        if pos.atr_checkpoint_extension_enabled:
            self._apply_atr_checkpoint_extensions(pos, float(high), float(low), timestamp)
        if pos.trailing_enabled:
            changed=self._maybe_trailing_exit(pos,i,float(high),float(low),timestamp,source)
            if pos.is_open: self._maybe_activate_break_even(pos,float(high),float(low),timestamp)
            return changed
        hit_tp=high>=pos.tp if pos.side==Side.LONG else low<=pos.tp; hit_sl=low<=pos.sl if pos.side==Side.LONG else high>=pos.sl
        if not(hit_tp or hit_sl):
            self._maybe_activate_break_even(pos,float(high),float(low),timestamp)
            return False
        if hit_tp and hit_sl: pos.ambiguous=True; use_tp=self.config.tie_policy==TiePolicy.OPTIMISTIC
        else: use_tp=hit_tp
        raw=pos.tp if use_tp else pos.sl; slip=1-self.config.slippage if pos.side==Side.LONG else 1+self.config.slippage
        reason=ExitReason.TP if use_tp else (pos.be_exit_reason if pos.be_triggered else (ExitReason.ATR_CHECKPOINT_PROFIT_LOCK if pos.atr_checkpoint_profit_lock_r is not None else ExitReason.SL))
        self._close_position(pos,i,raw*slip,reason,source,timestamp); return True

    def _maybe_activate_break_even(self,pos,high,low,timestamp):
        activation=pos.profile_break_even_activation_r
        if activation is None or pos.be_triggered or not pos.is_open:
            return False
        reached=(
            high>=pos.entry_price+activation*pos.risk
            if pos.side==Side.LONG
            else low<=pos.entry_price-activation*pos.risk
        )
        if not reached:
            return False
        new_sl=(
            pos.entry_price+pos.be_offset_r*pos.risk
            if pos.side==Side.LONG
            else pos.entry_price-pos.be_offset_r*pos.risk
        )
        improves=new_sl>pos.sl if pos.side==Side.LONG else new_sl<pos.sl
        if not improves:
            return False
        pos.sl=new_sl
        pos.final_active_stop=new_sl
        pos.be_triggered=True
        pos.be_trigger_time=pd.Timestamp(timestamp)
        pos.be_stop_price=new_sl
        pos.be_exit_reason=ExitReason.BE_R_OFFSET if pos.be_offset_r else ExitReason.BE
        return True

'''
text = replace_between(
    text,
    "    def _maybe_exit_bar(self,pos,i,high,low,timestamp,source):\n",
    "    def _maybe_r_step_trailing_exit(self, pos, i, high, low, timestamp, source):\n",
    new_exit_bar,
    "engine exit dispatcher",
)

new_partial_sl = '''    def _maybe_partial_sl_exit(self,pos,i,high,low,timestamp,source):
        """Close SL1 percentage once, then leave the remainder for TP or SL2.

        If Break-even Protection was activated on an earlier processed bar, its
        stop takes priority over the deeper SL ladder for the remaining size.
        """
        if pos.trailing_enabled and pos.trailing_active:
            if self._maybe_trailing_exit(pos,i,high,low,timestamp,source): return True
        is_long=pos.side==Side.LONG
        adverse=lambda price: low<=price if is_long else high>=price
        tp_hit=high>=pos.tp if is_long else low<=pos.tp
        protective_stop_hit=bool(pos.be_triggered and adverse(pos.sl))
        sl1_hit=adverse(pos.sl1_price) and not pos.sl1_hit
        sl2_hit=adverse(pos.sl2_price)
        slip=1-self.config.slippage if is_long else 1+self.config.slippage
        sl1_execution=pos.sl1_price*slip
        if tp_hit and (not (protective_stop_hit or sl1_hit or sl2_hit) or self.config.tie_policy==TiePolicy.OPTIMISTIC):
            raw=pos.tp; price=raw*slip
            self._partial_sl_fill(pos,pos.remaining_quantity,price,"tp",i,timestamp,source)
            self._finalize_partial_sl(pos,ExitReason.TP)
            return True
        if protective_stop_hit:
            self._partial_sl_fill(pos,pos.remaining_quantity,pos.sl*slip,"stop",i,timestamp,source)
            self._finalize_partial_sl(pos,pos.be_exit_reason or ExitReason.BE)
            return True
        if sl2_hit:
            if not pos.sl1_hit:
                self._partial_sl_fill(pos,pos.sl1_quantity,sl1_execution,"sl1",i,timestamp,source)
            self._partial_sl_fill(pos,pos.remaining_quantity,pos.sl2_price*slip,"sl2",i,timestamp,source)
            self._finalize_partial_sl(pos,ExitReason.SL)
            return True
        if sl1_hit:
            self._partial_sl_fill(pos,pos.sl1_quantity,sl1_execution,"sl1",i,timestamp,source)
            return True
        if pos.trailing_enabled and not pos.trailing_active:
            if self._maybe_trailing_exit(pos,i,high,low,timestamp,source): return True
        return False

'''
text = replace_between(
    text,
    "    def _maybe_partial_sl_exit(self,pos,i,high,low,timestamp,source):\n",
    "    def _maybe_combined_partial_exit(self,pos,i,high,low,timestamp,source):\n",
    new_partial_sl,
    "engine partial-SL exit",
)

new_combined = '''    def _maybe_combined_partial_exit(self,pos,i,high,low,timestamp,source):
        """Resolve TP1/TP2 and SL1/SL2 ladders.

        Profit Taking never moves the stop. If Break-even Protection activated
        on an earlier processed bar, that protective stop takes priority over
        the deeper partial-stop ladder for the remaining size.
        """
        if pos.trailing_enabled and pos.trailing_active:
            if self._maybe_trailing_exit(pos,i,high,low,timestamp,source): return True
        is_long=pos.side==Side.LONG
        adverse=lambda price: low<=price if is_long else high>=price
        favourable=lambda price: high>=price if is_long else low<=price
        tp1_hit=favourable(pos.tp1_price) and not pos.tp1_hit
        tp2_hit=favourable(pos.tp2_price) and pos.tp1_hit
        protective_stop_hit=bool(pos.be_triggered and adverse(pos.sl))
        sl1_hit=not pos.sl1_hit and adverse(pos.sl1_price)
        sl2_hit=adverse(pos.sl2_price)
        slip=1-self.config.slippage if is_long else 1+self.config.slippage

        def execute_losses():
            changed=False
            if protective_stop_hit:
                self._partial_fill(pos,pos.remaining_quantity,pos.sl*slip,"stop",i,timestamp,source)
                self._finalize_partial(pos,pos.be_exit_reason or ExitReason.BE)
                return True
            if sl2_hit:
                if not pos.sl1_hit:
                    changed=self._partial_sl_fill(pos,pos.sl1_quantity,pos.sl1_price*slip,"sl1",i,timestamp,source) or changed
                if pos.is_open:
                    self._partial_fill(pos,pos.remaining_quantity,pos.sl2_price*slip,"stop",i,timestamp,source)
                    self._finalize_partial(pos,ExitReason.SL)
                return True
            if sl1_hit:
                changed=self._partial_sl_fill(pos,pos.sl1_quantity,pos.sl1_price*slip,"sl1",i,timestamp,source) or changed
                if not pos.is_open:
                    self._finalize_partial(pos,ExitReason.SL)
            return changed

        if self.config.tie_policy==TiePolicy.PESSIMISTIC and (protective_stop_hit or sl1_hit or sl2_hit):
            return execute_losses()

        changed=False
        if tp1_hit:
            changed=self._partial_fill(pos,pos.tp1_quantity,pos.tp1_price,"tp1",i,timestamp,source) or changed
            if not pos.is_open:
                self._finalize_partial(pos,ExitReason.TP)
                return True
            tp2_hit=favourable(pos.tp2_price)
        if pos.is_open and pos.tp1_hit and tp2_hit:
            self._partial_fill(pos,pos.remaining_quantity,pos.tp2_price,"tp2",i,timestamp,source)
            self._finalize_partial(pos,ExitReason.TP)
            return True
        if pos.is_open:
            changed=execute_losses() or changed
        if pos.is_open and pos.trailing_enabled and not pos.trailing_active:
            if self._maybe_trailing_exit(pos,i,high,low,timestamp,source): return True
        return changed

'''
text = replace_between(
    text,
    "    def _maybe_combined_partial_exit(self,pos,i,high,low,timestamp,source):\n",
    "    def _partial_sl_fill(self,pos,quantity,price,stage,i,timestamp,source):\n",
    new_combined,
    "engine combined partial exit",
)

# Delete the old post-TP1 stop mutator and remove its call from partial TP.
start = text.find("    def _after_tp1(self,pos):\n")
end = text.find("    def _maybe_partial_exit(self,pos,i,high,low,timestamp,source):\n", start)
if start < 0 or end < 0:
    raise RuntimeError("Stage 21 could not locate _after_tp1")
text = text[:start] + text[end:]
text = must_replace(
    text,
    '            changed=self._partial_fill(pos,pos.tp1_quantity,pos.tp1_price,"tp1",i,timestamp,source); self._after_tp1(pos)\n',
    '            changed=self._partial_fill(pos,pos.tp1_quantity,pos.tp1_price,"tp1",i,timestamp,source)\n',
    "partial TP _after_tp1 call",
)

# Improve final-stage labels when a BE stop closes the remainder.
text = must_replace(
    text,
    '        pos.final_exit_reason=("SL1_THEN_TP" if reason==ExitReason.TP and pos.sl1_hit else ("SL1_THEN_SL2" if reason==ExitReason.SL and pos.sl1_hit else reason.value))\n',
    '        if pos.sl1_hit and reason==ExitReason.TP:\n'
    '            pos.final_exit_reason="SL1_THEN_TP"\n'
    '        elif pos.sl1_hit and reason==ExitReason.SL:\n'
    '            pos.final_exit_reason="SL1_THEN_SL2"\n'
    '        elif pos.sl1_hit:\n'
    '            pos.final_exit_reason=f"SL1_THEN_{reason.value}"\n'
    '        else:\n'
    '            pos.final_exit_reason=reason.value\n',
    "partial-SL final reason",
)
text = must_replace(
    text,
    '        elif reason==ExitReason.TRAILING_STOP: stages.append("TRAILING_STOP")\n'
    '        elif reason==ExitReason.R_STEP_TRAILING_STOP: stages.append("R_STEP_TRAILING_STOP")\n',
    '        elif reason in (ExitReason.BE,ExitReason.BE_R_OFFSET): stages.append(reason.value)\n'
    '        elif reason==ExitReason.TRAILING_STOP: stages.append("TRAILING_STOP")\n'
    '        elif reason==ExitReason.R_STEP_TRAILING_STOP: stages.append("R_STEP_TRAILING_STOP")\n',
    "partial TP BE final reason",
)

# Result rows no longer report a removed behavior knob.
text = "\n".join(
    line for line in text.splitlines()
    if "after_tp1_stop_mode" not in line and "after_tp1_stop_offset_r" not in line
) + "\n"
write(path, text)


# 6) Rewrite focused partial-take-profit tests around the new ownership model.
path = "tests/test_partial_take_profit.py"
write(path, '''import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig, RiskMode, TiePolicy
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import StrategyProfile, default_profiles


def candles(*bars):
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i),
                "open": 100,
                "close": 100,
                "high": high,
                "low": low,
                "volume": 1,
            }
            for i, (high, low) in enumerate(bars)
        ]
    )


def base_profile(**changes):
    values = dict(
        enabled=True,
        stop_loss_multiple=2,
        partial_profit_enabled=True,
        tp1_r=1,
        tp1_close_pct=50,
        tp2_r=2,
    )
    values.update(changes)
    return StrategyProfile(**values)


def open_long(*bars, profile=None, fee=0, tie_policy=TiePolicy.PESSIMISTIC):
    profiles = default_profiles()
    profiles["sideways_long"] = profile or base_profile()
    cfg = BacktestConfig(
        risk_mode=RiskMode.FIXED,
        fixed_r=10,
        atr_period=1,
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        strategy_profiles=profiles,
        maker_fee=0,
        taker_fee=fee,
        slippage=0,
        tie_policy=tie_policy,
    )
    engine = BacktestEngine(candles(*bars), cfg)
    engine.market_regime_values[:] = "SIDEWAYS"
    engine.plus_di_values[:] = 50
    engine.minus_di_values[:] = 10
    engine.di_spread[:] = 40
    engine._open_pair(0)
    pair = engine.active_pairs[0]
    assert pair.long is not None and pair.short is None
    return engine, pair.long


def test_long_tp1_then_stop_closes_only_remainder():
    engine, position = open_long((100, 100), (120, 99), (105, 79))
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.is_open
    assert position.sl == pytest.approx(80)
    assert engine._scan_exit(position, 2)
    assert not position.tp2_hit
    assert position.stop_exit_quantity == pytest.approx(position.original_quantity / 2)
    assert position.final_exit_reason == "TP1_THEN_SL"


def test_long_tp1_then_tp2_and_fee_reconciliation():
    engine, position = open_long((100, 100), (140, 99), fee=0.001, tie_policy=TiePolicy.OPTIMISTIC)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.tp2_hit
    assert position.remaining_quantity == 0
    expected = (
        position.entry_fee
        + position.tp1_exit_price * position.tp1_quantity * 0.001
        + position.tp2_exit_price * position.tp2_quantity * 0.001
    )
    assert position.fees == pytest.approx(expected)
    assert position.net_pnl == pytest.approx(position.gross_pnl - expected)


def test_pessimistic_same_candle_stop_precedes_tp1():
    engine, position = open_long((100, 100), (120, 79), tie_policy=TiePolicy.PESSIMISTIC)
    assert engine._scan_exit(position, 1)
    assert not position.tp1_hit
    assert position.final_exit_reason == "SL"


def test_optimistic_same_candle_runs_tp1_then_tp2():
    engine, position = open_long((100, 100), (140, 79), tie_policy=TiePolicy.OPTIMISTIC)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.tp2_hit
    assert position.stop_exit_time is None or pd.isna(position.stop_exit_time)


def test_partial_take_profit_does_not_move_stop_by_itself():
    engine, position = open_long((100, 100), (120, 99))
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.is_open
    assert position.sl == pytest.approx(80)
    assert not position.be_triggered


def test_break_even_protection_controls_remaining_stop_after_tp1():
    profile = base_profile(break_even_enabled=True, break_even_activation_r=1, break_even_offset_r=0)
    engine, position = open_long((100, 100), (120, 99), (100, 99), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.is_open
    assert position.be_triggered
    assert position.sl == pytest.approx(100)
    assert engine._scan_exit(position, 2)
    assert position.stop_exit_price == pytest.approx(100)
    assert position.final_exit_reason == "TP1_THEN_BE"


def test_break_even_profit_offset_controls_remaining_stop_after_tp1():
    profile = base_profile(break_even_enabled=True, break_even_activation_r=1, break_even_offset_r=0.5)
    engine, position = open_long((100, 100), (120, 106), (106, 104), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.be_triggered
    assert position.sl == pytest.approx(105)
    assert engine._scan_exit(position, 2)
    assert position.stop_exit_price == pytest.approx(105)
    assert position.final_exit_reason == "TP1_THEN_BE_R_OFFSET"


def test_combined_profile_ladders_allow_sl1_then_tp1_then_tp2():
    profile = base_profile(partial_stop_enabled=True, sl1_r=0.5, sl1_close_pct=25, sl2_r=2)
    engine, position = open_long((100, 100), (100, 95), (120, 100), (140, 100), profile=profile)
    assert engine._scan_exit(position, 1)
    assert engine._scan_exit(position, 2)
    assert engine._scan_exit(position, 3)
    assert position.sl1_hit and position.tp1_hit and position.tp2_hit
    assert position.sl1_quantity + position.tp1_quantity + position.tp2_quantity == pytest.approx(position.original_quantity)
    assert position.remaining_quantity == 0


def test_combined_partial_profit_uses_break_even_as_the_only_stop_override():
    profile = base_profile(
        partial_stop_enabled=True,
        sl1_r=0.5,
        sl1_close_pct=25,
        sl2_r=2,
        break_even_enabled=True,
        break_even_activation_r=1,
        break_even_offset_r=0,
    )
    engine, position = open_long((100, 100), (120, 100), (100, 99), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and not position.sl1_hit
    assert position.be_triggered and position.sl == pytest.approx(100)
    assert engine._scan_exit(position, 2)
    assert not position.sl1_hit
    assert position.stop_exit_price == pytest.approx(100)
    assert position.final_exit_reason == "TP1_THEN_BE"
''')


# 7) Current Strategy Profile tests: no post-TP1 field; prove old field is rejected.
path = "tests/test_strategy_profiles.py"
text = read(path)
text = must_replace(
    text,
    '        tp2_r=3,\n        after_tp1_stop_mode="MOVE_TO_ENTRY",\n',
    '        tp2_r=3,\n        break_even_enabled=True,\n        break_even_activation_r=1,\n        break_even_offset_r=0,\n',
    "strategy-profile exit-plan fixture",
)
text = must_replace(
    text,
    '    assert position.tp1_quantity / position.original_quantity == pytest.approx(0.40)\n    assert position.after_tp1_stop_mode == "MOVE_TO_ENTRY"\n',
    '    assert position.tp1_quantity / position.original_quantity == pytest.approx(0.40)\n    assert position.profile_break_even_activation_r == pytest.approx(1)\n',
    "strategy-profile exit-plan assertion",
)
text += '''\n\ndef test_removed_post_tp1_stop_field_is_rejected():
    raw = profiles_to_dict(default_profiles())
    raw["bull_long"]["after_tp1_stop_mode"] = "MOVE_TO_ENTRY"
    with pytest.raises(ValueError, match="unknown profile settings: after_tp1_stop_mode"):
        normalize_profiles(raw)
'''
write(path, text)


# 8) GUI contract: the duplicate controls must not exist.
path = "tests/test_gui_main_window.py"
text = read(path)
if "def test_partial_profit_has_no_duplicate_post_tp1_stop_controls():" not in text:
    text += '''\n\ndef test_partial_profit_has_no_duplicate_post_tp1_stop_controls():
    app(); window=MainWindow()
    try:
        controls=window.profile_editor.controls
        assert "after_tp1_stop_mode" not in controls
        assert "after_tp1_stop_offset_r" not in controls
        assert "break_even_enabled" in controls
        assert "break_even_activation_r" in controls
        assert "break_even_offset_r" in controls
    finally: window.close()
'''
write(path, text)


# Production contract: the removed feature name must be gone completely.
legacy_terms = ("after_tp1_stop_mode", "after_tp1_stop_offset_r", "AfterTP1StopMode", "partial_sl_overridden_after_tp1")
leftovers = []
for source in Path("crypto_strategy_lab").rglob("*.py"):
    body = source.read_text(encoding="utf-8")
    for term in legacy_terms:
        if term in body:
            leftovers.append(f"{source}: {term}")
if leftovers:
    raise RuntimeError("Stage 21 production leftovers:\n" + "\n".join(leftovers))

print("Stage 21 migration applied; retired post-TP1 stop contract is absent from production code.")
