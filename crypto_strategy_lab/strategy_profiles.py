"""Regime/direction strategy profiles and legacy-safe serialization helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PROFILE_KEYS = ("bull_long", "bull_short", "bear_long", "bear_short", "sideways_long", "sideways_short")


@dataclass(frozen=True)
class StrategyProfile:
    enabled: bool = False
    flip_direction: bool = False
    filter_action: str = "REJECT"
    secondary_flip_enabled: bool = False
    secondary_flip_indicator: str = "CLOSE_LOCATION"
    secondary_flip_minimum: float = 0.0
    secondary_flip_maximum: float = 1.0
    additional_flip_rules: tuple = ()
    entry_rules: tuple = ()
    flip_rule_match_mode: str = "ANY"
    reject_rule_match_mode: str = "ANY"
    reward_risk_ratio: float = 1.0
    risk_multiplier: float = 1.0
    stop_loss_multiple: float = 2.0
    partial_stop_enabled: bool = False
    sl1_r: float = 0.5
    sl1_close_pct: float = 50.0
    sl2_r: float = 2.0
    partial_profit_enabled: bool = False
    tp1_r: float = 1.0
    tp1_close_pct: float = 50.0
    tp2_r: float = 2.0
    after_tp1_stop_mode: str = "KEEP_ORIGINAL_SL"
    after_tp1_stop_offset_r: float = 0.0
    di_spread_enabled: bool = False
    di_spread_minimum: float = 0.0
    di_spread_maximum: float = 1000.0
    adx_enabled: bool = False
    adx_minimum: float = 0.0
    adx_maximum: float = 1000.0
    atr_pct_enabled: bool = False
    atr_pct_minimum: float = 0.0
    atr_pct_maximum: float = 1.0
    rsi_enabled: bool = False
    rsi_period: int = 14
    rsi_minimum: float = 0.0
    rsi_maximum: float = 100.0
    bb_width_enabled: bool = False
    bb_width_minimum: float = 0.0
    bb_width_maximum: float = 1000.0
    close_location_enabled: bool = False
    close_location_minimum: float = 0.0
    close_location_maximum: float = 1.0
    momentum_enabled: bool = False
    momentum_lookback_hours: int = 24
    momentum_minimum: float = -10.0
    momentum_maximum: float = 10.0
    vwap_distance_enabled: bool = False
    vwap_distance_minimum: float = -1000.0
    vwap_distance_maximum: float = 1000.0
    trailing_enabled: bool = False
    trailing_activation_r: float = 3.0
    trailing_distance_r: float = 1.0
    break_even_enabled: bool = False
    break_even_activation_r: float = 1.0
    break_even_offset_r: float = 0.0
    timeout_enabled: bool = False
    timeout_minutes: int = 480

    def validate(self, key: str = "profile") -> None:
        if self.reward_risk_ratio <= 0 or self.risk_multiplier <= 0:
            raise ValueError(f"{key}: reward/risk and risk multiplier must be positive")
        if self.stop_loss_multiple <= 0: raise ValueError(f"{key}: stop-loss multiple must be positive")
        if self.sl1_r <= 0 or self.sl2_r <= self.sl1_r: raise ValueError(f"{key}: SL2 must be greater than SL1")
        if self.tp1_r <= 0 or self.tp2_r <= self.tp1_r: raise ValueError(f"{key}: TP2 must be greater than TP1")
        if not 0 < self.sl1_close_pct < 100 or not 0 < self.tp1_close_pct < 100: raise ValueError(f"{key}: partial close percentages must be between 0 and 100")
        if self.after_tp1_stop_mode not in ("KEEP_ORIGINAL_SL","MOVE_TO_ENTRY","MOVE_TO_R_OFFSET"): raise ValueError(f"{key}: invalid post-TP1 stop mode")
        if self.filter_action not in ("REJECT","FLIP"): raise ValueError(f"{key}: invalid entry-filter action")
        if self.flip_direction and self.filter_action == "FLIP": raise ValueError(f"{key}: whole-profile flip cannot be combined with conditional filter flip")
        if self.secondary_flip_indicator not in ("DI_SPREAD","ADX","ATR_PCT","RSI","BB_WIDTH","CLOSE_LOCATION","MOMENTUM","VWAP_DISTANCE"): raise ValueError(f"{key}: invalid secondary flip indicator")
        if self.secondary_flip_minimum > self.secondary_flip_maximum: raise ValueError(f"{key}: secondary flip minimum must not exceed maximum")
        for number, rule in enumerate(self.additional_flip_rules, 1):
            if not isinstance(rule, dict): raise ValueError(f"{key}: flip rule {number} must be an object")
            if rule.get("indicator") not in ("DI_SPREAD","ADX","ATR_PCT","RSI","BB_WIDTH","CLOSE_LOCATION","MOMENTUM","VWAP_DISTANCE"): raise ValueError(f"{key}: flip rule {number} has an invalid indicator")
            if float(rule.get("minimum", 0)) > float(rule.get("maximum", 0)): raise ValueError(f"{key}: flip rule {number} minimum must not exceed maximum")
        if self.flip_rule_match_mode not in ("ANY","ALL") or self.reject_rule_match_mode not in ("ANY","ALL"): raise ValueError(f"{key}: rule match modes must be ANY or ALL")
        for number, rule in enumerate(self.entry_rules, 1):
            if not isinstance(rule, dict): raise ValueError(f"{key}: entry rule {number} must be an object")
            if rule.get("action") not in ("FLIP","REJECT"): raise ValueError(f"{key}: entry rule {number} has an invalid action")
            if rule.get("condition","INSIDE") not in ("INSIDE","OUTSIDE"): raise ValueError(f"{key}: entry rule {number} has an invalid condition")
            if rule.get("indicator") not in ("DI_SPREAD","ADX","ATR_PCT","RSI","BB_WIDTH","CLOSE_LOCATION","MOMENTUM","VWAP_DISTANCE"): raise ValueError(f"{key}: entry rule {number} has an invalid indicator")
            if float(rule.get("minimum",0)) > float(rule.get("maximum",0)): raise ValueError(f"{key}: entry rule {number} minimum must not exceed maximum")
        if self.after_tp1_stop_offset_r < 0: raise ValueError(f"{key}: post-TP1 stop offset cannot be negative")
        for label, lo, hi in (
            ("DI spread", self.di_spread_minimum, self.di_spread_maximum), ("ADX", self.adx_minimum, self.adx_maximum),
            ("ATR %", self.atr_pct_minimum, self.atr_pct_maximum), ("RSI", self.rsi_minimum, self.rsi_maximum),
            ("BB width", self.bb_width_minimum, self.bb_width_maximum), ("close location", self.close_location_minimum, self.close_location_maximum),
            ("momentum", self.momentum_minimum, self.momentum_maximum), ("VWAP distance", self.vwap_distance_minimum, self.vwap_distance_maximum)):
            if lo > hi: raise ValueError(f"{key}: {label} minimum must not exceed maximum")
        if not 0 <= self.rsi_minimum <= self.rsi_maximum <= 100: raise ValueError(f"{key}: RSI must be within 0-100")
        if not 0 <= self.close_location_minimum <= self.close_location_maximum <= 1: raise ValueError(f"{key}: close location must be within 0-100%")
        if self.rsi_period < 1 or self.momentum_lookback_hours < 1 or self.timeout_minutes < 1: raise ValueError(f"{key}: periods must be positive")
        if self.break_even_activation_r <= 0: raise ValueError(f"{key}: break-even activation must be positive")


def default_profiles() -> dict[str, StrategyProfile]:
    return {key: StrategyProfile(enabled=True) for key in PROFILE_KEYS}


def profiles_to_dict(profiles: dict[str, StrategyProfile]) -> dict[str, dict[str, Any]]:
    return {key: asdict(profiles.get(key, StrategyProfile())) for key in PROFILE_KEYS}


def normalize_profiles(value: Any) -> dict[str, StrategyProfile]:
    source = value if isinstance(value, dict) else {}
    result = {}
    for key in PROFILE_KEYS:
        raw = source.get(key, {})
        if isinstance(raw, StrategyProfile):
            result[key]=raw
        else:
            raw=dict(raw)
            rules=list(raw.get("additional_flip_rules", ()))
            if raw.get("secondary_flip_enabled") and not rules:
                rules.append({"indicator":raw.get("secondary_flip_indicator","CLOSE_LOCATION"),"minimum":raw.get("secondary_flip_minimum",0.0),"maximum":raw.get("secondary_flip_maximum",1.0)})
            raw["additional_flip_rules"]=tuple(rules)
            entry_rules=list(raw.get("entry_rules", ()))
            if not entry_rules:
                action=str(raw.get("filter_action","REJECT")); condition="INSIDE" if action=="FLIP" else "OUTSIDE"
                legacy=(
                    ("di_spread","DI_SPREAD"),("adx","ADX"),("atr_pct","ATR_PCT"),("rsi","RSI"),("bb_width","BB_WIDTH"),("close_location","CLOSE_LOCATION"),("momentum","MOMENTUM"),("vwap_distance","VWAP_DISTANCE"))
                for prefix,indicator in legacy:
                    if raw.get(prefix+"_enabled"):
                        entry_rules.append({"action":action,"indicator":indicator,"condition":condition,"minimum":raw.get(prefix+"_minimum",0.0),"maximum":raw.get(prefix+"_maximum",1000.0)})
                for rule in rules:
                    entry_rules.append({"action":"FLIP","indicator":rule["indicator"],"condition":"INSIDE","minimum":rule["minimum"],"maximum":rule["maximum"]})
                if action=="FLIP" and rules: raw["flip_rule_match_mode"]="ANY"
            raw["entry_rules"]=tuple(entry_rules)
            result[key]=StrategyProfile(**raw)
        result[key].validate(key)
    return result


def profile_key(regime: str, direction: str) -> str:
    return f"{regime.lower()}_{direction.lower()}"
