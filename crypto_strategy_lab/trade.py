"""Trade state and result models."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class Side(str, Enum): LONG="LONG"; SHORT="SHORT"
class ExitReason(str, Enum): TP="TP"; SL="SL"; ATR_CHECKPOINT_PROFIT_LOCK="ATR_CHECKPOINT_PROFIT_LOCK"; R_STEP_TRAILING_STOP="R_STEP_TRAILING_STOP"; TRAILING_STOP="TRAILING_STOP"; BE="BE"; BE_COST_ADJUSTED="BE_COST_ADJUSTED"; BE_R_OFFSET="BE_R_OFFSET"; BOTH_OPEN_TIMEOUT="BOTH_OPEN_TIMEOUT"; REMAINING_LEG_TIMEOUT_AFTER_FIRST_SL="REMAINING_LEG_TIMEOUT_AFTER_FIRST_SL"; END_OF_DATA="END_OF_DATA"
class ExitSource(str, Enum): INTRABAR="1M_INTRABAR"; FALLBACK_15M="15M_FALLBACK"; END_OF_DATA="END_OF_DATA"

@dataclass
class Position:
    side: Side; entry_time: object; entry_index: int; entry_price: float; risk: float; sl: float; tp: float; quantity: float; risk_amount: float; entry_notional: float; atr_at_entry: float
    uncapped_quantity: float = 0.0; effective_leverage: float = 0.0; distance_unit: float = 0.0; entry_fee: float = 0.0; exit_fee: float = 0.0
    exit_time: Optional[object] = None; exit_index: Optional[int] = None; exit_price: Optional[float] = None; exit_reason: Optional[ExitReason] = None; exit_source: Optional[ExitSource] = None
    original_sl: float = 0.0; be_enabled: bool = False; be_triggered: bool = False; be_trigger_time: Optional[object] = None; be_triggered_by_side: Optional[Side] = None; be_mode: Optional[str] = None; be_offset_r: float = 0.0; be_stop_price: Optional[float] = None; be_exit_reason: Optional[ExitReason] = None; be_same_candle_ambiguous: bool = False; be_active_after: Optional[object] = None; gross_pnl: float = 0.0; fees: float = 0.0; gross_r: float = 0.0; net_pnl: float = 0.0; net_r: float = 0.0; price_r: float = 0.0; ambiguous: bool = False; missing_intrabar_data: bool = False; fallback_reason: Optional[str] = None
    trailing_enabled: bool = False; trailing_active: bool = False; trailing_activation_price: Optional[float] = None; trailing_activation_time: Optional[object] = None; favourable_price: Optional[float] = None; trailing_stop: Optional[float] = None; final_active_stop: Optional[float] = None; trailing_exit_price: Optional[float] = None; trailing_profit_r: Optional[float] = None
    trailing_distance_r: Optional[float] = None
    profile_break_even_activation_r: Optional[float] = None
    atr_checkpoint_extension_enabled: bool = False; atr_checkpoint_di_spread_minimum: float = 30.0; atr_checkpoint_bb_width_minimum: float = 0.03; atr_checkpoint_profit_lock_start: float = 3.0; atr_checkpoint_profit_lock_distance: float = 1.0; atr_checkpoint_next_r: float = 1.0; atr_checkpoint_count: int = 0; atr_checkpoint_pass_count: int = 0; atr_checkpoint_fail_count: int = 0; atr_checkpoint_last_time: Optional[object] = None; atr_checkpoint_last_r: Optional[float] = None; atr_checkpoint_last_di_spread: Optional[float] = None; atr_checkpoint_last_bb_width: Optional[float] = None; atr_checkpoint_last_passed: bool = False; atr_checkpoint_initial_tp: Optional[float] = None; atr_checkpoint_final_tp_r: Optional[float] = None; atr_checkpoint_profit_lock_r: Optional[float] = None
    r_step_trailing_enabled: bool = False; r_step_activation_r: float = 2.0; r_step_distance_r: float = 2.0; r_step_size_r: float = 1.0; r_step_maximum_r: float = 0.0; r_step_trailing_active: bool = False; r_step_next_checkpoint_r: float = 2.0; r_step_checkpoint_count: int = 0; r_step_last_checkpoint_r: Optional[float] = None; r_step_last_checkpoint_time: Optional[object] = None; r_step_locked_r: Optional[float] = None; r_step_initial_tp: Optional[float] = None
    r_step_activation_partial_taken: bool = False; r_step_activation_close_pct: float = 0.0; r_step_activation_quantity: float = 0.0; r_step_runner_quantity: float = 0.0
    partial_tp_enabled: bool = False; original_quantity: float = 0.0; remaining_quantity: float = 0.0; tp1_quantity: float = 0.0; tp2_quantity: float = 0.0
    partial_sl_enabled: bool = False; sl1_price: Optional[float] = None; sl2_price: Optional[float] = None; sl1_quantity: float = 0.0; sl1_hit: bool = False
    sl1_exit_time: Optional[object] = None; sl1_exit_price: Optional[float] = None; sl1_gross_pnl: Optional[float] = None; sl1_fees: Optional[float] = None; sl1_net_pnl: Optional[float] = None
    tp1_price: Optional[float] = None; tp2_price: Optional[float] = None; tp1_hit: bool = False; tp2_hit: bool = False
    tp1_exit_time: Optional[object] = None; tp1_exit_price: Optional[float] = None; tp1_gross_pnl: Optional[float] = None; tp1_fees: Optional[float] = None; tp1_net_pnl: Optional[float] = None
    tp2_exit_time: Optional[object] = None; tp2_exit_price: Optional[float] = None; tp2_gross_pnl: Optional[float] = None; tp2_fees: Optional[float] = None; tp2_net_pnl: Optional[float] = None
    stop_exit_time: Optional[object] = None; stop_exit_price: Optional[float] = None; stop_exit_quantity: Optional[float] = None; stop_gross_pnl: Optional[float] = None; stop_fees: Optional[float] = None; stop_net_pnl: Optional[float] = None
    realized_pnl: float = 0.0; final_exit_reason: Optional[str] = None
    first_sl_partial_original_quantity: float = 0.0; first_sl_partial_quantity: float = 0.0; first_sl_partial_gross_pnl: float = 0.0; first_sl_partial_fee: float = 0.0; first_sl_partial_net_pnl: float = 0.0
    sr_nearest_support: Optional[float] = None; sr_nearest_resistance: Optional[float] = None
    sr_support_distance_atr: float = float('nan'); sr_resistance_distance_atr: float = float('nan')
    sr_support_distance_price: float = float('nan'); sr_resistance_distance_price: float = float('nan')
    sr_near_support: bool = False; sr_near_resistance: bool = False
    sr_inside_support_zone: bool = False; sr_inside_resistance_zone: bool = False
    sr_location: str = "NO_STRUCTURE"; sr_trade_location_rating: str = "NEUTRAL"
    sr_room_in_direction_atr: float = float('nan')
    sr_support_state: str = "NO_SUPPORT_NEARBY"; sr_resistance_state: str = "NO_RESISTANCE_NEARBY"
    sr_support_tested: bool = False; sr_resistance_tested: bool = False
    sr_support_held: bool = False; sr_resistance_held: bool = False
    sr_support_rejection_atr: float = float('nan'); sr_resistance_rejection_atr: float = float('nan')
    sr_support_test_count: int = 0; sr_resistance_test_count: int = 0
    sr_bars_since_support_test: Optional[int] = None; sr_bars_since_resistance_test: Optional[int] = None
    sr_support_last_test_index: Optional[int] = None; sr_resistance_last_test_index: Optional[int] = None
    sr_support_last_test_time: Optional[object] = None; sr_resistance_last_test_time: Optional[object] = None
    sr_confirmation_rating: str = "NEUTRAL"
    sr_support_zone_low: Optional[float] = None; sr_support_zone_high: Optional[float] = None
    sr_resistance_zone_low: Optional[float] = None; sr_resistance_zone_high: Optional[float] = None
    sr_level_price: Optional[float] = None; sr_zone_low: Optional[float] = None; sr_zone_high: Optional[float] = None
    @property
    def is_open(self) -> bool: return self.exit_time is None

@dataclass
class TradePair:
    pair_id: int; long: Optional[Position]; short: Optional[Position]; equity_before_trade: float; strategy_candle_open_time: object; strategy_entry_time: object; strategy_entry_price: float; leverage_capped: bool = False; pair_be_triggered: bool = False; equity_after_trade: Optional[float] = None; both_open_timeout_triggered: bool = False; timeout_minutes: Optional[int] = None; timeout_exit_time: Optional[object] = None
    remaining_leg_timeout_after_first_sl_started: bool = False; first_sl_side: Optional[Side] = None; first_sl_time: Optional[object] = None; remaining_leg_timeout_deadline: Optional[object] = None; remaining_leg_timeout_triggered: bool = False; remaining_leg_timeout_exit_time: Optional[object] = None; remaining_leg_timeout_exit_side: Optional[Side] = None
    remaining_leg_timeout_checkpoint_count: int = 0; remaining_leg_timeout_extension_count: int = 0; remaining_leg_timeout_last_checkpoint_time: Optional[object] = None; remaining_leg_timeout_last_checkpoint_profit_r: Optional[float] = None
    checkpoint_score_last_atr_pct: Optional[float] = None; checkpoint_score_last_directional_di: Optional[float] = None; checkpoint_score_last_bb_width_pct: Optional[float] = None; checkpoint_score_last_pass_count: int = 0; checkpoint_score_last_condition_count: int = 0; checkpoint_score_last_passed: bool = False
    checkpoint_zero_score_streak: int = 0; checkpoint_zero_score_max_streak: int = 0; checkpoint_zero_score_last_time: Optional[object] = None; checkpoint_zero_score_confirmed_close: bool = False
    first_sl_survivor_partial_taken: bool = False; first_sl_survivor_partial_side: Optional[Side] = None; first_sl_survivor_partial_time: Optional[object] = None; first_sl_survivor_partial_pct: float = 0.0; first_sl_survivor_partial_quantity: float = 0.0; first_sl_survivor_partial_exit_price: Optional[float] = None; first_sl_survivor_partial_gross_pnl: float = 0.0; first_sl_survivor_partial_fee: float = 0.0; first_sl_survivor_partial_net_pnl: float = 0.0
    checkpoint_reentry_gate_started: bool = False; checkpoint_reentry_gate_side: Optional[Side] = None; checkpoint_reentry_gate_tp: Optional[float] = None; checkpoint_reentry_gate_sl: Optional[float] = None; checkpoint_reentry_gate_start_time: Optional[object] = None; checkpoint_reentry_gate_release_time: Optional[object] = None; checkpoint_reentry_gate_release_reason: Optional[str] = None
    market_structure: Optional[dict] = None
    def positions(self):
        if self.long is None:
            return () if self.short is None else (self.short,)
        if self.short is None:
            return (self.long,)
        return (self.long, self.short)
    @property
    def is_open(self) -> bool:
        return bool(
            (self.long is not None and self.long.is_open)
            or (self.short is not None and self.short.is_open)
        )
