from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"missing Stage 18 anchor: {label}")


def replace_test(text: str, name: str, replacement: str) -> str:
    pattern = rf"(?ms)^def {re.escape(name)}\(.*?(?=^def |^class |\Z)"
    match = re.search(pattern, text)
    if match:
        return text[:match.start()] + replacement.rstrip() + "\n\n\n" + text[match.end():]
    if f"def {name}(" in replacement and replacement.rstrip() in text:
        return text
    raise SystemExit(f"missing test: {name}")


def drop_tests_with_retired_rr(text: str) -> str:
    pattern = re.compile(r"(?ms)^def (test_[A-Za-z0-9_]+)\(.*?(?=^def |^class |\Z)")
    retired = (
        "enable_di_regime_reward_risk",
        "enable_bull_long_conditional_reward_risk",
        "bull_long_conditional_reward_risk",
        "di_reward_risk_ratio",
        "di_long_reward_risk_ratio",
        "di_short_reward_risk_ratio",
        "di_long_bull_reward_risk_ratio",
        "di_short_bull_reward_risk_ratio",
        "di_long_bear_reward_risk_ratio",
        "di_short_bear_reward_risk_ratio",
        "di_long_sideways_reward_risk_ratio",
        "di_short_sideways_reward_risk_ratio",
    )
    chunks = []
    pos = 0
    for m in pattern.finditer(text):
        block = m.group(0)
        if any(token in block for token in retired):
            chunks.append(text[pos:m.start()])
            pos = m.end()
    chunks.append(text[pos:])
    return "".join(chunks)


# tests/test_backtester.py -------------------------------------------------
p = ROOT / "tests" / "test_backtester.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "from crypto_strategy_lab.trade import Position, Side\n",
    "from crypto_strategy_lab.trade import Position, Side\nfrom crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile\n",
    "backtester profile imports",
)
old_cfg = '''def cfg(**kw):
    base = dict(risk_mode=RiskMode.FIXED, fixed_r=10, initial_equity=1000, risk_per_leg=0.01,
                sl_mult=1, tp_mult=1, taker_fee=0, maker_fee=0, slippage=0,
                entry_mode=EntryMode.WAIT_UNTIL_CLOSED)
    base.update(kw)
    return BacktestConfig(**base)
'''
new_cfg = '''def profile_set(**changes):
    profile = StrategyProfile(enabled=True, **changes)
    return {key: profile for key in PROFILE_KEYS}


def _profile_value(value):
    return getattr(value, "value", value)


def _profiles_for_legacy_config(values):
    sl = float(values.get("sl_mult", 2.0))
    tp = float(values.get("tp_mult", 3.0))
    partial_profit = bool(values.get("enable_partial_take_profit", False))
    partial_stop = bool(values.get("enable_partial_stop_loss", False))
    stop_multiple = float(values.get("stop_loss_r", sl)) if partial_profit else sl
    profile = StrategyProfile(
        enabled=True,
        stop_loss_multiple=stop_multiple,
        reward_risk_ratio=tp / sl if sl else 1.0,
        partial_stop_enabled=partial_stop,
        sl1_r=float(values.get("sl1_r", 0.5)),
        sl1_close_pct=float(values.get("sl1_close_pct", 50.0)),
        sl2_r=float(values.get("sl2_r", 8.0)),
        partial_profit_enabled=partial_profit,
        tp1_r=float(values.get("tp1_r", 3.0)),
        tp1_close_pct=float(values.get("tp1_close_pct", 50.0)),
        tp2_r=float(values.get("tp2_r", 12.0)),
        after_tp1_stop_mode=_profile_value(values.get("after_tp1_stop_mode", "KEEP_ORIGINAL_SL")),
        after_tp1_stop_offset_r=float(values.get("after_tp1_stop_offset_r", 0.0)),
        trailing_enabled=bool(values.get("enable_trailing_profit", False)),
        trailing_activation_r=float(values.get("trail_activation_r", 3.0)),
        trailing_distance_r=float(values.get("trail_distance_r", 1.0)),
    )
    return {key: profile for key in PROFILE_KEYS}


def cfg(**kw):
    base = dict(risk_mode=RiskMode.FIXED, fixed_r=10, initial_equity=1000, risk_per_leg=0.01,
                sl_mult=1, tp_mult=1, taker_fee=0, maker_fee=0, slippage=0,
                entry_mode=EntryMode.WAIT_UNTIL_CLOSED)
    base.update(kw)
    base["enable_strategy_profiles"] = True
    base.setdefault("strategy_profiles", _profiles_for_legacy_config(base))
    return BacktestConfig(**base)
'''
s = replace_once(s, old_cfg, new_cfg, "backtester cfg helper")
s = replace_test(s, "test_atr_checkpoint_extends_biased_tp_and_locks_profit", '''def test_atr_checkpoint_extends_biased_tp_and_locks_profit():
    df = candles([(100, 100, 100, 100)] * 4)
    engine = BacktestEngine(
        df,
        cfg(
            enable_di_direction_sizing=True,
            strategy_profiles=profile_set(
                atr_checkpoint_tp_extension_enabled=True,
                atr_checkpoint_di_spread_minimum=30,
                atr_checkpoint_bb_width_minimum=0.03,
            ),
        ),
    )
    engine.plus_di_values[:] = 50
    engine.minus_di_values[:] = 10
    engine.bb_width[:] = 0.04
    pos = Position(Side.LONG, df.timestamp.iloc[0], 0, 100, 10, 80, 120, 1, 10, 100, 10)
    pos.original_sl = 80
    pos.atr_checkpoint_extension_enabled = True
    pos.atr_checkpoint_initial_tp = 120
    pos.atr_checkpoint_final_tp_r = 2

    engine._apply_atr_checkpoint_extensions(pos, 130, 100, df.timestamp.iloc[2])

    assert pos.atr_checkpoint_pass_count == 3
    assert pos.tp == pytest.approx(150)
    assert pos.sl == pytest.approx(120)
    assert pos.atr_checkpoint_profit_lock_r == pytest.approx(2)''')
s = replace_test(s, "test_atr_checkpoint_failure_leaves_original_exit_levels", '''def test_atr_checkpoint_failure_leaves_original_exit_levels():
    df = candles([(100, 100, 100, 100)] * 4)
    engine = BacktestEngine(
        df,
        cfg(
            enable_di_direction_sizing=True,
            strategy_profiles=profile_set(atr_checkpoint_tp_extension_enabled=True),
        ),
    )
    engine.plus_di_values[:] = 35
    engine.minus_di_values[:] = 10
    engine.bb_width[:] = 0.04
    pos = Position(Side.LONG, df.timestamp.iloc[0], 0, 100, 10, 80, 120, 1, 10, 100, 10)
    pos.original_sl = 80
    pos.atr_checkpoint_extension_enabled = True

    engine._apply_atr_checkpoint_extensions(pos, 110, 100, df.timestamp.iloc[2])

    assert pos.atr_checkpoint_fail_count == 1
    assert pos.tp == pytest.approx(120)
    assert pos.sl == pytest.approx(80)''')
s = replace_test(s, "test_bull_long_r_step_staircase_advances_stop_and_ignores_fixed_tp", '''def test_bull_long_r_step_staircase_advances_stop_and_ignores_fixed_tp():
    df = candles([(100, 100, 100, 100)] * 5)
    engine = BacktestEngine(
        df,
        cfg(
            enable_di_direction_sizing=True,
            strategy_profiles=profile_set(
                r_step_trailing_enabled=True,
                r_step_activation_r=2,
                r_step_distance_r=2,
                r_step_size_r=1,
                r_step_maximum_r=0,
            ),
        ),
    )
    pos = Position(Side.LONG, df.timestamp.iloc[0], 0, 100, 10, 90, 120, 1, 10, 100, 10)
    pos.original_sl = 90
    pos.r_step_trailing_enabled = True
    pos.r_step_initial_tp = 120

    assert not engine._maybe_r_step_trailing_exit(pos, 1, 120, 101, df.timestamp.iloc[1], None)
    assert pos.is_open
    assert pos.sl == pytest.approx(100)
    assert pos.r_step_checkpoint_count == 1

    assert not engine._maybe_r_step_trailing_exit(pos, 2, 130, 111, df.timestamp.iloc[2], None)
    assert pos.sl == pytest.approx(110)
    assert pos.r_step_last_checkpoint_r == pytest.approx(3)

    assert engine._maybe_r_step_trailing_exit(pos, 3, 115, 109, df.timestamp.iloc[3], None)
    assert pos.exit_reason.value == "R_STEP_TRAILING_STOP"
    assert pos.exit_price == pytest.approx(110)''')
s = replace_test(s, "test_bull_long_r_step_staircase_banks_partial_at_activation", '''def test_bull_long_r_step_staircase_banks_partial_at_activation():
    df = candles([(100, 100, 100, 100)] * 4)
    engine = BacktestEngine(
        df,
        cfg(
            enable_di_direction_sizing=True,
            strategy_profiles=profile_set(
                r_step_trailing_enabled=True,
                r_step_activation_close_pct=80,
            ),
        ),
    )
    pos = Position(Side.LONG, df.timestamp.iloc[0], 0, 100, 10, 90, 120, 1, 10, 100, 10)
    pos.original_sl = 90
    pos.r_step_trailing_enabled = True
    pos.r_step_activation_close_pct = 80
    pos.partial_tp_enabled = True
    pos.original_quantity = 1
    pos.remaining_quantity = 1
    pos.tp1_quantity = 0.8
    pos.tp1_price = 120
    pos.r_step_activation_quantity = 0.8
    pos.r_step_runner_quantity = 0.2

    assert not engine._maybe_r_step_trailing_exit(pos, 1, 120, 101, df.timestamp.iloc[1], None)
    assert pos.r_step_activation_partial_taken
    assert pos.remaining_quantity == pytest.approx(0.2)
    assert pos.tp1_gross_pnl == pytest.approx(16)
    assert pos.sl == pytest.approx(100)

    assert engine._maybe_r_step_trailing_exit(pos, 2, 105, 99, df.timestamp.iloc[2], None)
    assert pos.exit_reason.value == "R_STEP_TRAILING_STOP"
    assert pos.gross_r == pytest.approx(1.6)
    assert pos.final_exit_reason == "TP1_THEN_R_STEP_TRAILING_STOP"''')
s = drop_tests_with_retired_rr(s)
p.write_text(s, encoding="utf-8")


# tests/test_coin_flip_sizing.py ------------------------------------------
p = ROOT / "tests" / "test_coin_flip_sizing.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "from crypto_strategy_lab.engine import BacktestEngine\n",
    "from crypto_strategy_lab.engine import BacktestEngine\nfrom crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile\n",
    "coin flip profile imports",
)
old = '''    values.update(overrides)
    return BacktestConfig(**values)
'''
new = '''    values.update(overrides)
    sl = float(values.get("sl_mult", 2.0))
    tp = float(values.get("tp_mult", 3.0))
    reward_risk = 1.0 if values.get("enable_di_direction_sizing", False) else tp / sl
    profile = StrategyProfile(enabled=True, stop_loss_multiple=sl, reward_risk_ratio=reward_risk)
    values["enable_strategy_profiles"] = True
    values.setdefault("strategy_profiles", {key: profile for key in PROFILE_KEYS})
    return BacktestConfig(**values)
'''
s = replace_once(s, old, new, "coin flip config helper")
helper_anchor = "\n\ndef test_heads_assigns_three_to_long_and_one_to_short_with_mirrored_one_to_one_levels():"
helper = '''

def direction_profiles(long_rr=1.0, short_rr=1.0, stop_loss_multiple=1.0):
    profiles = {}
    for key in PROFILE_KEYS:
        rr = long_rr if key.endswith("_long") else short_rr
        profiles[key] = StrategyProfile(enabled=True, stop_loss_multiple=stop_loss_multiple, reward_risk_ratio=rr)
    return profiles


def test_heads_assigns_three_to_long_and_one_to_short_with_mirrored_one_to_one_levels():'''
s = replace_once(s, helper_anchor, helper, "coin flip direction profile helper")
s = replace_test(s, "test_di_preferred_side_only_supports_two_to_one_reward_risk", '''def test_di_preferred_side_only_supports_two_to_one_reward_risk():
    engine = di_engine(50, 15)
    engine.config = BacktestConfig(
        **{
            **engine.config.__dict__,
            "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY,
            "strategy_profiles": direction_profiles(long_rr=2.0, short_rr=2.0),
        }
    )
    row = engine.run().iloc[0]
    stop_distance = row.long_entry_price - row.long_sl
    target_distance = row.long_tp - row.long_entry_price
    assert target_distance == pytest.approx(2 * stop_distance)
    assert row.di_applied_long_reward_risk_ratio == pytest.approx(2.0)''')
s = replace_test(s, "test_di_preferred_side_only_supports_asymmetric_reward_risk", '''def test_di_preferred_side_only_supports_asymmetric_reward_risk():
    long_engine = di_engine(50, 15)
    long_engine.config = BacktestConfig(
        **{
            **long_engine.config.__dict__,
            "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY,
            "strategy_profiles": direction_profiles(long_rr=2.0, short_rr=1.0),
        }
    )
    long_row = long_engine.run().iloc[0]
    assert long_row.long_tp - long_row.long_entry_price == pytest.approx(
        2 * (long_row.long_entry_price - long_row.long_sl)
    )

    short_engine = di_engine(10, 45)
    short_engine.config = BacktestConfig(
        **{
            **short_engine.config.__dict__,
            "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY,
            "strategy_profiles": direction_profiles(long_rr=2.0, short_rr=1.0),
        }
    )
    short_row = short_engine.run().iloc[0]
    assert short_row.short_entry_price - short_row.short_tp == pytest.approx(
        short_row.short_sl - short_row.short_entry_price
    )''')
s = drop_tests_with_retired_rr(s)
p.write_text(s, encoding="utf-8")


# tests/test_partial_take_profit.py ---------------------------------------
p = ROOT / "tests" / "test_partial_take_profit.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, "from crypto_strategy_lab.engine import BacktestEngine\n", "from crypto_strategy_lab.engine import BacktestEngine\nfrom crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile\n", "partial TP profile imports")
old = '''def config(**kw):
    base=dict(risk_mode=RiskMode.FIXED,fixed_r=10,atr_period=1,use_intrabar_data=False,enable_trade_telemetry=False,
              enable_partial_take_profit=True,tp1_r=1,tp2_r=2,stop_loss_r=2,tp1_close_pct=50,tp2_close_pct=50,
              maker_fee=0,taker_fee=0,slippage=0,trade_direction=TradeDirectionMode.LONG_ONLY)
    return BacktestConfig(**{**base,**kw})
'''
new = '''def _profile_value(value):
    return getattr(value, "value", value)


def _profiles_for(values):
    partial_profit = bool(values.get("enable_partial_take_profit", False))
    partial_stop = bool(values.get("enable_partial_stop_loss", False))
    sl = float(values.get("sl_mult", 2.0))
    tp = float(values.get("tp_mult", 3.0))
    profile = StrategyProfile(
        enabled=True,
        stop_loss_multiple=float(values.get("stop_loss_r", sl)) if partial_profit else sl,
        reward_risk_ratio=tp / sl,
        partial_profit_enabled=partial_profit,
        tp1_r=float(values.get("tp1_r", 1.0)),
        tp1_close_pct=float(values.get("tp1_close_pct", 50.0)),
        tp2_r=float(values.get("tp2_r", 2.0)),
        after_tp1_stop_mode=_profile_value(values.get("after_tp1_stop_mode", "KEEP_ORIGINAL_SL")),
        after_tp1_stop_offset_r=float(values.get("after_tp1_stop_offset_r", 0.0)),
        partial_stop_enabled=partial_stop,
        sl1_r=float(values.get("sl1_r", 0.5)),
        sl1_close_pct=float(values.get("sl1_close_pct", 50.0)),
        sl2_r=float(values.get("sl2_r", 2.0)),
        trailing_enabled=bool(values.get("enable_trailing_profit", False)),
        trailing_activation_r=float(values.get("trail_activation_r", 3.0)),
        trailing_distance_r=float(values.get("trail_distance_r", 1.0)),
    )
    return {key: profile for key in PROFILE_KEYS}


def config(**kw):
    base=dict(risk_mode=RiskMode.FIXED,fixed_r=10,atr_period=1,use_intrabar_data=False,enable_trade_telemetry=False,
              enable_partial_take_profit=True,tp1_r=1,tp2_r=2,stop_loss_r=2,tp1_close_pct=50,tp2_close_pct=50,
              maker_fee=0,taker_fee=0,slippage=0,trade_direction=TradeDirectionMode.LONG_ONLY)
    base.update(kw)
    base["enable_strategy_profiles"] = True
    base.setdefault("strategy_profiles", _profiles_for(base))
    return BacktestConfig(**base)
'''
s = replace_once(s, old, new, "partial TP config helper")
s = replace_test(s, "test_disabled_mode_is_identical_to_legacy_configuration", '''def test_disabled_mode_is_identical_to_non_partial_profile_configuration():
    data=candles((100,100),(111,89))
    common=dict(risk_mode=RiskMode.FIXED,fixed_r=10,atr_period=1,use_intrabar_data=False,enable_trade_telemetry=False,
                sl_mult=1,tp_mult=1,maker_fee=0,taker_fee=0,slippage=0,enable_strategy_profiles=True,
                strategy_profiles={key:StrategyProfile(enabled=True,stop_loss_multiple=1,reward_risk_ratio=1) for key in PROFILE_KEYS})
    baseline=BacktestEngine(data,BacktestConfig(**common)).run()
    disabled=BacktestEngine(data,BacktestConfig(**common,enable_partial_take_profit=False)).run()
    pd.testing.assert_frame_equal(baseline,disabled)''')
p.write_text(s, encoding="utf-8")


# tests/test_partial_stop_loss.py -----------------------------------------
p = ROOT / "tests" / "test_partial_stop_loss.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, "from crypto_strategy_lab.engine import BacktestEngine\n", "from crypto_strategy_lab.engine import BacktestEngine\nfrom crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile\n", "partial SL profile imports")
anchor = "\n\ndef run(*bars):"
helper = '''

def partial_stop_profiles(*, sl1_r, sl1_close_pct, sl2_r, target_r, trailing=False, trailing_distance_r=1.0):
    profile = StrategyProfile(
        enabled=True,
        stop_loss_multiple=1.0,
        reward_risk_ratio=float(target_r),
        partial_stop_enabled=True,
        sl1_r=float(sl1_r),
        sl1_close_pct=float(sl1_close_pct),
        sl2_r=float(sl2_r),
        trailing_enabled=trailing,
        trailing_distance_r=float(trailing_distance_r),
    )
    return {key: profile for key in PROFILE_KEYS}


def run(*bars):'''
s = replace_once(s, anchor, helper, "partial SL helper")
s = replace_once(s, "        tie_policy=TiePolicy.PESSIMISTIC,\n    )", "        tie_policy=TiePolicy.PESSIMISTIC,\n        enable_strategy_profiles=True,\n        strategy_profiles=partial_stop_profiles(sl1_r=.5, sl1_close_pct=50, sl2_r=8, target_r=8),\n    )", "partial SL run config")
s = replace_once(s, "        slippage=0,\n    )\n    results = BacktestEngine(candles((100, 100), (110, 100)), cfg).run()", "        slippage=0,\n        enable_strategy_profiles=True,\n        strategy_profiles=partial_stop_profiles(sl1_r=2, sl1_close_pct=75, sl2_r=10, target_r=10),\n    )\n    results = BacktestEngine(candles((100, 100), (110, 100)), cfg).run()", "partial SL reporting config")
s = replace_once(s, "        slippage=0,\n    )\n    engine = BacktestEngine(candles((100, 100), (100, 94), (96, 89)), cfg)", "        slippage=0,\n        enable_strategy_profiles=True,\n        strategy_profiles=partial_stop_profiles(sl1_r=.5, sl1_close_pct=50, sl2_r=2, target_r=3, trailing=True, trailing_distance_r=.5),\n    )\n    engine = BacktestEngine(candles((100, 100), (100, 94), (96, 89)), cfg)", "partial SL trailing config")
p.write_text(s, encoding="utf-8")


# tests/test_remaining_leg_timeout.py -------------------------------------
p = ROOT / "tests" / "test_remaining_leg_timeout.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, "from crypto_strategy_lab.statistics import summarize\n", "from crypto_strategy_lab.statistics import summarize\nfrom crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile\n", "remaining-leg profile imports")
old = '''    values.update(overrides)
    return BacktestConfig(**values)
'''
new = '''    values.update(overrides)
    sl = float(values.get("sl_mult", 1.0))
    tp = float(values.get("tp_mult", 5.0))
    profile = StrategyProfile(enabled=True, stop_loss_multiple=sl, reward_risk_ratio=tp / sl)
    values["enable_strategy_profiles"] = True
    values.setdefault("strategy_profiles", {key: profile for key in PROFILE_KEYS})
    return BacktestConfig(**values)
'''
s = replace_once(s, old, new, "remaining-leg config helper")
p.write_text(s, encoding="utf-8")


# tests/test_support_resistance.py ----------------------------------------
p = ROOT / "tests" / "test_support_resistance.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, "from crypto_strategy_lab.engine import BacktestEngine\n", "from crypto_strategy_lab.engine import BacktestEngine\nfrom crypto_strategy_lab.strategy_profiles import default_profiles\n", "SR profile import")
s = replace_once(s, "        disabled = BacktestEngine(data, BacktestConfig(enable_support_resistance_analysis=False)).run()", "        disabled = BacktestEngine(data, BacktestConfig(enable_strategy_profiles=True, strategy_profiles=default_profiles(), enable_support_resistance_analysis=False)).run()", "SR disabled regression config")
s = replace_once(s, "            enable_support_resistance_analysis=True, sr_filter_mode=\"ANALYSIS_ONLY\",\n        )).run()", "            enable_strategy_profiles=True, strategy_profiles=default_profiles(),\n            enable_support_resistance_analysis=True, sr_filter_mode=\"ANALYSIS_ONLY\",\n        )).run()", "SR enabled regression config")
# The second enabled config has the same original text; replace it too.
s = s.replace("            enable_support_resistance_analysis=True, sr_filter_mode=\"ANALYSIS_ONLY\",\n        )).run()", "            enable_strategy_profiles=True, strategy_profiles=default_profiles(),\n            enable_support_resistance_analysis=True, sr_filter_mode=\"ANALYSIS_ONLY\",\n        )).run()", 1)
p.write_text(s, encoding="utf-8")


# tests/test_trailing_profit.py -------------------------------------------
p = ROOT / "tests" / "test_trailing_profit.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, "from crypto_strategy_lab.trade import ExitReason, ExitSource, Position, Side, TradePair\n", "from crypto_strategy_lab.trade import ExitReason, ExitSource, Position, Side, TradePair\nfrom crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile\n", "trailing profile imports")
s = replace_test(s, "test_apply_to_is_independent_and_reuses_stored_r", '''def test_profiles_enable_trailing_independently_by_direction_and_reuse_stored_r():
    e=engine()
    profiles={}
    for key in PROFILE_KEYS:
        profiles[key]=StrategyProfile(
            enabled=True,
            stop_loss_multiple=2,
            reward_risk_ratio=1.5,
            trailing_enabled=key.endswith("_long"),
            trailing_activation_r=3,
            trailing_distance_r=1,
        )
    e.config=BacktestConfig(
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        risk_mode=RiskMode.FIXED,
        fixed_r=2,
        enable_strategy_profiles=True,
        strategy_profiles=profiles,
    )
    e._open_pair(0)
    pair=e.active_pairs[0]
    assert pair.long.trailing_enabled and not pair.short.trailing_enabled
    assert pair.long.trailing_activation_price == pair.long.entry_price + pair.long.risk*3''')
p.write_text(s, encoding="utf-8")

print("Stage 18 Strategy Profile test migration applied")
