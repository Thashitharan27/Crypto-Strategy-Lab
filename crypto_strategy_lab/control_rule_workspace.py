"""High-level, GUI-parity rule workspace for MCP backtest control.

This module deliberately targets the researcher-facing Strategy Builder model,
not the low-level ``StrategyProfileConfig.entry_rules`` wire format.  Conditions
inside one group are ANDed and groups are OR alternatives, exactly as in the
current GUI/engine.  The adapter round-trips through the existing builder
compiler so MCP-authored rules remain visible and editable in the GUI.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import re
from typing import Any
from uuid import uuid4

from crypto_strategy_lab.data_lake_config import (
    PROFILE_KEYS,
    ResearchRunConfig,
    normalize_data_lake_config,
)
from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS
from crypto_strategy_lab.strategy_rule_model import (
    DIRECTION_MODES,
    MARKET_PERMISSIONS,
    RULE_KINDS,
    compile_profiles,
    decompile_rules,
    infer_direction_mode,
    infer_market_permissions,
    is_categorical_evidence,
    is_context_timeframe_evidence,
    is_support_resistance_evidence,
    normalize_rule,
    rule_value_options,
)


FAMILY_TO_KIND = {
    "ENTRY": "REQUIRED",
    "REQUIRED": "REQUIRED",
    "VETO": "VETO",
    "FLIP": "FLIP",
}
KIND_TO_FAMILY = {"REQUIRED": "ENTRY", "VETO": "VETO", "FLIP": "FLIP"}
MCP_NUMERIC_CONDITIONS = (
    "EQUALS",
    "NOT_EQUALS",
    "GT",
    "GTE",
    "LT",
    "LTE",
    "BETWEEN",
    "OUTSIDE",
)
MCP_CATEGORICAL_CONDITIONS = ("EQUALS", "NOT_EQUALS")

MARKET_REGIME_METHODS = {
    "BTC_STRUCTURAL": "BTC structural trend (market-wide)",
    "ASSET_STRUCTURAL": "Selected asset structural trend",
    "ASSET_RETURN": "Asset trailing return",
}
SIGNAL_STRATEGIES = {
    "DI": "DI Direction",
    "DMI_TREND": "DMI Trend — Baseline",
    "MACD_PULLBACK": "MACD Pullback — 12/26/9",
    "EMA_9_20_PULLBACK": "EMA 9/20 Pullback — Scalping",
    "MTF_SR_REACTION": "MTF S/R Reaction — 4H / 1H / Entry TF",
}

# Kept in this pure-Python module so the control server does not need to import
# Qt just to discover researcher-facing labels.
EVIDENCE_LABELS = {
    "DI_SPREAD": "DI Spread",
    "DIRECTIONAL_DI": "Directional DI",
    "DIRECTIONAL_DI_RATIO": "Directional DI Ratio",
    "DI_PRESSURE_STATE": "DI Pressure State",
    "DI_SPREAD_CHANGE": "DI Spread Change",
    "DIRECTIONAL_DI_CHANGE": "Directional DI Change",
    "OPPOSING_DI_CHANGE": "Opposing DI Change",
    "ADX": "ADX",
    "ADX_CHANGE": "ADX Change (1 bar)",
    "ATR_PCT": "ATR % (decimal)",
    "EMA_9_DISTANCE_ATR": "Price − EMA 9 (ATR)",
    "EMA_20_DISTANCE_ATR": "Price − EMA 20 (ATR)",
    "EMA_9_20_SPREAD_ATR": "EMA 9 − EMA 20 (ATR)",
    "EMA_9_SLOPE_ATR": "EMA 9 Slope (ATR / bar)",
    "EMA_20_SLOPE_ATR": "EMA 20 Slope (ATR / bar)",
    "VOLUME_RATIO_20": "Volume / Prior 20-Bar Average",
    "VOLUME_CHANGE_PCT": "Volume Change (1 bar, decimal)",
    "EMA_50_DISTANCE_ATR": "Price − EMA 50 (ATR)",
    "EMA_100_DISTANCE_ATR": "Price − EMA 100 (ATR)",
    "EMA_200_DISTANCE_ATR": "Price − EMA 200 (ATR)",
    "EMA_STACK_STATE": "EMA Stack State (50 / 100 / 200)",
    "PRICE_VS_EMA_STACK": "Price vs EMA Stack (50 / 100 / 200)",
    "MACD_LINE": "MACD Line (12/26)",
    "MACD_SIGNAL": "MACD Signal (9)",
    "MACD_HISTOGRAM": "MACD Histogram",
    "MACD_HISTOGRAM_CHANGE": "MACD Histogram Change (1 bar)",
    "MACD_CROSS_STATE": "MACD Cross State",
    "MACD_ZERO_STATE": "MACD Zero State",
    "RSI": "RSI",
    "BB_WIDTH": "BB Width (decimal)",
    "CLOSE_LOCATION": "Close Location",
    "CANDLE_BODY_ATR": "Candle Body (ATR)",
    "CANDLE_RANGE_ATR": "Candle Range (ATR)",
    "BODY_TO_RANGE_RATIO": "Candle Body / Range",
    "LOWER_WICK_RATIO": "Lower Wick / Range",
    "UPPER_WICK_RATIO": "Upper Wick / Range",
    "RANGE_CONTRACTION_RATIO": "Range / Previous Range",
    "BODY_CONTRACTION_RATIO": "Body / Previous Body",
    "CANDLE_CLOSE_LOCATION": "Candle Close Location",
    "BULLISH_ENGULFING": "Bullish Engulfing",
    "BEARISH_ENGULFING": "Bearish Engulfing",
    "BULLISH_PIN_BAR": "Bullish Pin Bar",
    "BEARISH_PIN_BAR": "Bearish Pin Bar",
    "BULLISH_REVERSAL_TRIGGER": "Bullish Reversal Trigger (Engulfing / Pin)",
    "BEARISH_REVERSAL_TRIGGER": "Bearish Reversal Trigger (Engulfing / Pin)",
    "MOMENTUM": "Momentum Return",
    "VWAP_DISTANCE": "VWAP Distance (ATR)",
    "MR_TRADE_STRETCH_ATR": "MR — Trade-Direction Stretch (ATR)",
    "MR_DISTANCE_ATR": "MR — Price − Mean (ATR)",
    "MR_MOTION": "MR — Motion",
    "MR_BB_ZSCORE": "MR — BB Z-Score",
    "MR_BB_LOCATION": "MR — BB Location",
    "MR_SIGNAL": "MR — Signal",
    "MR_TRADE_ALIGNMENT": "MR — Trade Alignment",
    "MR_STRENGTH": "MR — Strength",
    "MR_STATE": "MR — State",
    "MR_DISTANCE_CHANGE_ATR": "MR — Distance Change (ATR, 1 bar)",
    "SR_NEAR_SUPPORT": "S/R — Near Support",
    "SR_NEAR_RESISTANCE": "S/R — Near Resistance",
    "SR_INSIDE_SUPPORT_ZONE": "S/R — Inside Support Zone",
    "SR_INSIDE_RESISTANCE_ZONE": "S/R — Inside Resistance Zone",
    "SR_SUPPORT_STATE": "S/R — Support State",
    "SR_RESISTANCE_STATE": "S/R — Resistance State",
    "SR_SUPPORT_HELD": "S/R — Support Held",
    "SR_RESISTANCE_HELD": "S/R — Resistance Held",
    "SR_TRADE_LOCATION_RATING": "S/R — Trade Location Rating",
    "SR_ROOM_IN_DIRECTION_ATR": "S/R — Room In Direction (ATR)",
    "SR_SUPPORT_DISTANCE_ATR": "S/R — Support Distance (ATR)",
    "SR_RESISTANCE_DISTANCE_ATR": "S/R — Resistance Distance (ATR)",
    "SR_SUPPORT_REJECTION_ATR": "S/R — Support Rejection (ATR)",
    "SR_RESISTANCE_REJECTION_ATR": "S/R — Resistance Rejection (ATR)",
    "SR_SUPPORT_TEST_COUNT": "S/R — Support Test Count",
    "SR_RESISTANCE_TEST_COUNT": "S/R — Resistance Test Count",
    "SR_BARS_SINCE_SUPPORT_TEST": "S/R — Bars Since Support Test",
    "SR_BARS_SINCE_RESISTANCE_TEST": "S/R — Bars Since Resistance Test",
    "SR_APPROACH_MOMENTUM_STATE": "S/R — Approach Momentum State",
    "SR_ROLE_REVERSAL_STATE": "S/R — Break / Retest State",
    "SR_ZONE_PENETRATION_ATR": "S/R — Zone Penetration (ATR)",
    "SR_ZONE_REJECTION_ATR": "S/R — Zone Rejection (ATR)",
    "SR_BREAKOUT_BODY_ATR": "S/R — Breakout Body (ATR)",
    "SR_BREAKOUT_CLOSE_BEYOND_ZONE_ATR": "S/R — Close Beyond Zone (ATR)",
    "SR_ENTRY_RELATION": "S/R — Entry Relation",
    "SR_FAVORABLE_STRUCTURE_STATE": "S/R — Favorable Structure State",
    "SR_OPPOSING_STRUCTURE_STATE": "S/R — Opposing Structure State",
    "SR_FAVORABLE_HELD": "S/R — Favorable Structure Held",
    "SR_OPPOSING_HELD": "S/R — Opposing Structure Held",
    "SR_TARGET_PATH": "S/R — Target Path vs Opposing Structure",
    "SR_FAVORABLE_DISTANCE_NATIVE_ATR": "S/R — Favorable Distance (Selected-TF ATR)",
    "SR_OPPOSING_DISTANCE_NATIVE_ATR": "S/R — Opposing Room (Selected-TF ATR)",
    "SR_FAVORABLE_DISTANCE_STRATEGY_ATR": "S/R — Favorable Distance (Strategy-TF ATR)",
    "SR_OPPOSING_DISTANCE_STRATEGY_ATR": "S/R — Opposing Room (Strategy-TF ATR)",
    "SR_OPPOSING_ROOM_R": "S/R — Opposing Room (R)",
    "SR_OPPOSING_ROOM_TARGET_MULTIPLE": "S/R — Opposing Room / Planned Target",
    "SR_FAVORABLE_REJECTION_NATIVE_ATR": "S/R — Favorable Rejection (Selected-TF ATR)",
    "SR_OPPOSING_REJECTION_NATIVE_ATR": "S/R — Opposing Rejection (Selected-TF ATR)",
    "SR_FAVORABLE_TEST_COUNT": "S/R — Favorable Structure Test Count",
    "SR_OPPOSING_TEST_COUNT": "S/R — Opposing Structure Test Count",
    "SR_BARS_SINCE_FAVORABLE_TEST": "S/R — Bars Since Favorable Test",
    "SR_BARS_SINCE_OPPOSING_TEST": "S/R — Bars Since Opposing Test",
    "OI_CHANGE_PCT_5M": "OI Change 5m (decimal)",
    "OI_CHANGE_PCT_1H": "OI Change 1h (decimal)",
    "OI_CHANGE_PCT_24H": "OI Change 24h (decimal)",
    "OI_ZSCORE_7D": "OI Z-Score (7d)",
    "PRICE_CHANGE_PCT_1H": "Price Change 1h (decimal)",
    "PRICE_OI_STATE": "Price / OI State (Strategy Bar)",
    "OI_VS_PRICE_STATE_1H": "Price / OI State (1h)",
    "TOP_TRADER_ACCOUNT_BIAS": "Top Trader Account Bias (ratio − 1)",
    "TOP_TRADER_POSITION_BIAS": "Top Trader Position Bias (ratio − 1)",
    "GLOBAL_LONG_SHORT_ACCOUNT_BIAS": "Global Long/Short Account Bias (ratio − 1)",
    "TAKER_LONG_SHORT_VOLUME_BIAS": "Taker Long/Short Volume Bias (ratio − 1)",
    "FUNDING_RATE_BPS": "Funding Rate (bps)",
    "FUNDING_BIAS": "Funding Bias",
    "FUNDING_24H_SUM_BPS": "Funding 24h Sum (bps)",
    "FUNDING_CHANGE_BPS": "Funding Change (bps)",
    "FUNDING_3_EVENT_MEAN_BPS": "Funding 3-Event Mean (bps)",
    "FUNDING_ZSCORE_7D": "Funding Z-Score (7d)",
    "FUNDING_EXTREME_POSITIVE": "Funding Extreme Positive",
    "FUNDING_EXTREME_NEGATIVE": "Funding Extreme Negative",
    "MARK_INDEX_BASIS_BPS": "Mark − Index Basis (bps)",
    "MARK_INDEX_BASIS_STATE": "Mark / Index Basis State",
    "MARK_INDEX_BASIS_ZSCORE_7D": "Mark / Index Basis Z-Score (7d)",
    "TRADE_MARK_BASIS_BPS": "Trade − Mark Basis (bps)",
    "TRADE_INDEX_BASIS_BPS": "Trade − Index Basis (bps)",
    "PREMIUM_INDEX_ZSCORE_7D": "Premium Index Z-Score (7d)",
    "TAKER_BUY_SELL_RATIO": "Taker Buy / Sell Ratio",
    "TAKER_DELTA_PCT": "Taker Delta (source interval, decimal)",
    "TAKER_DELTA_PCT_15M": "Taker Delta 15m (decimal)",
    "TAKER_DELTA_PCT_1H": "Taker Delta 1h (decimal)",
    "TAKER_FLOW_PERSISTENCE": "Taker Flow Persistence (0–1)",
}

LEGACY_SR_AUTHORING_EVIDENCE = frozenset(
    {
        "SR_TRADE_LOCATION_RATING",
        "SR_ROOM_IN_DIRECTION_ATR",
        "SR_NEAR_SUPPORT",
        "SR_NEAR_RESISTANCE",
        "SR_INSIDE_SUPPORT_ZONE",
        "SR_INSIDE_RESISTANCE_ZONE",
        "SR_SUPPORT_STATE",
        "SR_RESISTANCE_STATE",
        "SR_SUPPORT_HELD",
        "SR_RESISTANCE_HELD",
        "SR_SUPPORT_DISTANCE_ATR",
        "SR_RESISTANCE_DISTANCE_ATR",
        "SR_SUPPORT_REJECTION_ATR",
        "SR_RESISTANCE_REJECTION_ATR",
        "SR_SUPPORT_TEST_COUNT",
        "SR_RESISTANCE_TEST_COUNT",
        "SR_BARS_SINCE_SUPPORT_TEST",
        "SR_BARS_SINCE_RESISTANCE_TEST",
    }
)
AUTHORABLE_RULE_INDICATORS = tuple(
    indicator
    for indicator in RULE_INDICATORS
    if indicator not in LEGACY_SR_AUTHORING_EVIDENCE
)

SR_TIMEFRAME_LABELS = {
    None: "CONFIGURED",
    0: "STRATEGY",
    60: "1H",
    240: "4H",
    1440: "1D",
}
_SR_TIMEFRAME_INPUTS = {
    "CONFIGURED": None,
    "LEGACY": None,
    "STRATEGY": 0,
    "STRATEGY_TF": 0,
    "0": 0,
    "1H": 60,
    "60": 60,
    "4H": 240,
    "240": 240,
    "1D": 1440,
    "1440": 1440,
}
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _humanize(value: str) -> str:
    return str(value).replace("_", " ").title()


def _normalize_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _bool(value: Any, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on", "active", "enabled"}:
            return True
        if normalized in {"false", "0", "no", "off", "muted", "disabled"}:
            return False
    raise ValueError(f"{name} must be boolean")


def _family(value: str) -> str:
    key = str(value).strip().upper()
    try:
        return KIND_TO_FAMILY[FAMILY_TO_KIND[key]]
    except KeyError as exc:
        raise ValueError("family must be ENTRY, VETO, or FLIP") from exc


def _kind(value: str) -> str:
    return FAMILY_TO_KIND[_family(value)]


def _profile(value: str) -> str:
    key = str(value).strip().lower()
    if key not in PROFILE_KEYS:
        raise ValueError("profile must be one of: " + ", ".join(PROFILE_KEYS))
    return key


def _profile_scope(profile: str) -> tuple[str, str]:
    key = _profile(profile)
    regime, side = key.upper().split("_", 1)
    return regime, side


def _profiles_for_scope(regime: str, side: str) -> list[str]:
    result = []
    for profile in PROFILE_KEYS:
        p_regime, p_side = _profile_scope(profile)
        if regime in {"ALL", p_regime} and side in {"ALL", p_side}:
            result.append(profile)
    return result


def _validate_id(value: Any, *, label: str) -> str:
    result = str(value or "").strip()
    if not _ID_RE.fullmatch(result):
        raise ValueError(
            f"{label} must be 1-128 characters using letters, digits, _, -, ., or :"
        )
    return result


def _resolve_indicator(value: Any) -> str:
    raw = str(value or "").strip()
    native = raw.upper()
    if native in RULE_INDICATORS:
        return native
    wanted = _normalize_alias(raw)
    for indicator in RULE_INDICATORS:
        if wanted in {
            _normalize_alias(indicator),
            _normalize_alias(EVIDENCE_LABELS.get(indicator, indicator)),
        }:
            return indicator
    raise ValueError(f"unsupported strategy indicator: {value}")


def _resolve_categorical_value(indicator: str, value: Any) -> str:
    raw = str(value or "").strip()
    candidate = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()
    options = rule_value_options(indicator)
    if candidate in options:
        return candidate
    wanted = _normalize_alias(raw)
    for option in options:
        if wanted == _normalize_alias(option):
            return option
    raise ValueError(
        f"unsupported value {value!r} for {indicator}; valid values: "
        + ", ".join(options)
    )


def _sr_timeframe(value: Any) -> int | None:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("S/R timeframe must be STRATEGY, 1H, 4H, 1D, or CONFIGURED")
    if isinstance(value, (int, float)):
        numeric = int(value)
        if float(value) != numeric or numeric not in {0, 60, 240, 1440}:
            raise ValueError("S/R timeframe must be STRATEGY, 1H, 4H, 1D, or CONFIGURED")
        return numeric
    key = str(value).strip().upper().replace(" ", "_")
    if key not in _SR_TIMEFRAME_INPUTS:
        raise ValueError("S/R timeframe must be STRATEGY, 1H, 4H, 1D, or CONFIGURED")
    return _SR_TIMEFRAME_INPUTS[key]


def strategy_capabilities() -> dict[str, Any]:
    indicators: dict[str, Any] = {}
    for indicator in AUTHORABLE_RULE_INDICATORS:
        categorical = is_categorical_evidence(indicator)
        indicators[indicator] = {
            "display_name": EVIDENCE_LABELS.get(indicator, _humanize(indicator)),
            "type": "categorical" if categorical else "numeric",
            "conditions": list(
                MCP_CATEGORICAL_CONDITIONS if categorical else MCP_NUMERIC_CONDITIONS
            ),
            "values": list(rule_value_options(indicator)) if categorical else None,
            "supports_sr_timeframe": is_context_timeframe_evidence(indicator),
        }
    return {
        "rule_group_model": {
            "families": ["ENTRY", "VETO", "FLIP"],
            "conditions_inside_group": "ALL",
            "groups_inside_family": "OR",
            "group_match_modes": ["ALL"],
            "note": (
                "The current GUI/engine ANDs conditions inside each group and ORs "
                "groups. Express A OR B as two groups; profile-wide legacy match "
                "modes are not used for builder groups."
            ),
        },
        "profiles": list(PROFILE_KEYS),
        "market_regime_methods": [
            {"id": key, "display_name": label}
            for key, label in MARKET_REGIME_METHODS.items()
        ],
        "signal_strategies": [
            {"id": key, "display_name": SIGNAL_STRATEGIES[key]}
            for key in DIRECTION_MODES
        ],
        "market_permissions": list(MARKET_PERMISSIONS),
        "indicators": indicators,
        "sr_timeframes": [
            {"value": value, "label": label}
            for value, label in SR_TIMEFRAME_LABELS.items()
        ],
    }


def _condition_to_rule(
    condition: dict[str, Any],
    *,
    kind: str,
    group_id: str,
    group_name: str,
    enabled: bool,
    regime: str,
    side: str,
) -> dict[str, Any]:
    if not isinstance(condition, dict):
        raise ValueError("each condition must be an object")
    indicator = _resolve_indicator(condition.get("indicator", condition.get("evidence")))
    categorical = is_categorical_evidence(indicator)
    raw_operator = str(
        condition.get("condition", condition.get("operator", "EQUALS" if categorical else "GTE"))
    ).strip().upper().replace(" ", "_")
    aliases = {
        "EQ": "EQUALS",
        "=": "EQUALS",
        "IS": "EQUALS",
        "NE": "NOT_EQUALS",
        "!=": "NOT_EQUALS",
        "IS_NOT": "NOT_EQUALS",
        ">": "GT",
        ">=": "GTE",
        "<": "LT",
        "<=": "LTE",
    }
    operator = aliases.get(raw_operator, raw_operator)
    rule_id = _validate_id(condition.get("id", uuid4().hex), label="condition id")

    rule: dict[str, Any] = {
        "id": rule_id,
        "group_id": group_id,
        "group_name": group_name,
        "group_enabled": enabled,
        "kind": kind,
        "evidence": indicator,
        "regime": regime,
        "side": side,
    }
    if categorical:
        if operator not in MCP_CATEGORICAL_CONDITIONS:
            raise ValueError(
                f"{indicator} is categorical; condition must be EQUALS or NOT_EQUALS"
            )
        if "value" not in condition:
            raise ValueError(f"{indicator} requires value")
        rule["operator"] = "IS" if operator == "EQUALS" else "IS_NOT"
        rule["value"] = _resolve_categorical_value(indicator, condition["value"])
        rule["value2"] = None
    else:
        if operator not in MCP_NUMERIC_CONDITIONS:
            raise ValueError(
                f"{indicator} is numeric; unsupported condition {operator}"
            )
        if operator in {"BETWEEN", "OUTSIDE"}:
            lower = condition.get("minimum", condition.get("value"))
            upper = condition.get("maximum", condition.get("value2"))
            if lower is None or upper is None:
                raise ValueError(f"{operator} requires minimum and maximum")
            rule["operator"] = operator
            rule["value"] = float(lower)
            rule["value2"] = float(upper)
        elif operator in {"EQUALS", "NOT_EQUALS"}:
            value = condition.get("value", condition.get("minimum"))
            if value is None:
                raise ValueError(f"{operator} requires value")
            rule["operator"] = "BETWEEN" if operator == "EQUALS" else "OUTSIDE"
            rule["value"] = float(value)
            rule["value2"] = float(value)
        else:
            value = condition.get("value")
            if value is None:
                # Friendly fallback for callers migrating from low-level ranges.
                value = condition.get("minimum")
                if value is None:
                    value = condition.get("maximum")
            if value is None:
                raise ValueError(f"{operator} requires value")
            rule["operator"] = operator
            rule["value"] = float(value)
            rule["value2"] = float(value)

    if is_context_timeframe_evidence(indicator):
        if "sr_timeframe" in condition:
            rule["sr_timeframe_minutes"] = _sr_timeframe(condition["sr_timeframe"])
        elif "sr_timeframe_minutes" in condition:
            raw = condition["sr_timeframe_minutes"]
            rule["sr_timeframe_minutes"] = None if raw is None else _sr_timeframe(raw)
        else:
            rule["sr_timeframe_minutes"] = 0
    return normalize_rule(rule, expected_kind=kind)


def _condition_from_rule(rule: dict[str, Any]) -> dict[str, Any]:
    indicator = rule["evidence"]
    operator = rule["operator"]
    result: dict[str, Any] = {
        "id": rule["id"],
        "indicator": indicator,
        "display_name": EVIDENCE_LABELS.get(indicator, _humanize(indicator)),
    }
    if is_categorical_evidence(indicator):
        result["condition"] = "EQUALS" if operator == "IS" else "NOT_EQUALS"
        result["value"] = rule["value"]
    elif operator in {"BETWEEN", "OUTSIDE"} and float(rule["value"]) == float(rule["value2"]):
        result["condition"] = "EQUALS" if operator == "BETWEEN" else "NOT_EQUALS"
        result["value"] = float(rule["value"])
    elif operator in {"BETWEEN", "OUTSIDE"}:
        result["condition"] = operator
        result["minimum"] = float(rule["value"])
        result["maximum"] = float(rule["value2"])
    else:
        result["condition"] = operator
        result["value"] = float(rule["value"])
    if is_context_timeframe_evidence(indicator):
        timeframe = rule.get("sr_timeframe_minutes")
        result["sr_timeframe_minutes"] = timeframe
        result["sr_timeframe"] = SR_TIMEFRAME_LABELS.get(timeframe, str(timeframe))
    return result


class RuleWorkspace:
    """Mutable high-level view over one strict v3 config's builder rules."""

    def __init__(self, config: dict[str, Any]):
        parsed = normalize_data_lake_config(deepcopy(config))
        if not isinstance(parsed, ResearchRunConfig):
            raise ValueError("Rule workspace requires a native v3 ResearchRunConfig")
        parsed.validate()
        self._parsed = parsed
        self._base_config = parsed.to_dict()
        self.direction_mode = infer_direction_mode(parsed.strategy.profiles)
        self.market_permissions = tuple(
            infer_market_permissions(parsed.strategy.profiles, self.direction_mode)
        )
        decompiled = decompile_rules(parsed.strategy.profiles)
        self.rules: dict[str, list[dict[str, Any]]] = {
            kind: list(decompiled.get(kind, ())) for kind in RULE_KINDS
        }

    def _groups_for_kind(self, kind: str) -> list[tuple[str, list[dict[str, Any]]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for rule in self.rules[kind]:
            group_id = rule["group_id"]
            if group_id not in grouped:
                order.append(group_id)
                grouped[group_id] = []
            grouped[group_id].append(rule)
        return [(group_id, grouped[group_id]) for group_id in order]

    @staticmethod
    def _serialize_group(kind: str, group_id: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
        first = rules[0]
        regime, side = first["regime"], first["side"]
        return {
            "id": group_id,
            "name": first["group_name"],
            "family": KIND_TO_FAMILY[kind],
            "enabled": bool(first.get("group_enabled", True)),
            "match_mode": "ALL",
            "scope": {"regime": regime, "side": side},
            "applies_to_profiles": _profiles_for_scope(regime, side),
            "conditions": [_condition_from_rule(rule) for rule in rules],
        }

    def _all_groups(self) -> list[dict[str, Any]]:
        result = []
        for kind in RULE_KINDS:
            for group_id, rules in self._groups_for_kind(kind):
                result.append(self._serialize_group(kind, group_id, rules))
        return result

    def _group_location(self, group_id: str) -> tuple[str, list[dict[str, Any]]]:
        wanted = str(group_id).strip()
        matches = []
        for kind in RULE_KINDS:
            for found_id, rules in self._groups_for_kind(kind):
                if found_id == wanted:
                    matches.append((kind, rules))
        if not matches:
            raise ValueError(f"Unknown rule group: {group_id}")
        if len(matches) > 1:
            raise ValueError(
                f"Rule group id {group_id!r} is ambiguous across families; replace those groups with unique ids"
            )
        return matches[0]

    def _known_group_ids(self) -> set[str]:
        return {group["id"] for group in self._all_groups()}

    def _known_rule_ids(self, *, excluding_group: str | None = None) -> set[str]:
        return {
            rule["id"]
            for kind in RULE_KINDS
            for rule in self.rules[kind]
            if excluding_group is None or rule["group_id"] != excluding_group
        }

    def _make_group_rules(
        self,
        *,
        profile: str,
        family: str,
        group: dict[str, Any],
        default_name: str,
        existing_group_ids: set[str],
        existing_rule_ids: set[str],
        forced_group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(group, dict):
            raise ValueError("each rule group must be an object")
        family = _family(family)
        kind = FAMILY_TO_KIND[family]
        regime, side = _profile_scope(profile)
        supplied_scope = group.get("scope")
        if supplied_scope is not None:
            if not isinstance(supplied_scope, dict):
                raise ValueError("group scope must be an object")
            wanted_regime = str(supplied_scope.get("regime", regime)).upper()
            wanted_side = str(supplied_scope.get("side", side)).upper()
            if (wanted_regime, wanted_side) != (regime, side):
                raise ValueError(
                    "profile-scoped MCP groups cannot broaden their market scope; use the exact target profile"
                )
        raw_mode = str(group.get("match_mode", "ALL")).strip().upper()
        if raw_mode in {"AND"}:
            raw_mode = "ALL"
        if raw_mode != "ALL":
            raise ValueError(
                "Current Strategy Builder groups use ALL/AND inside a group. "
                "Represent OR logic as multiple groups, which are OR alternatives."
            )
        group_id = forced_group_id or group.get("id", group.get("group_id")) or uuid4().hex
        group_id = _validate_id(group_id, label="group id")
        if forced_group_id is None and group_id in existing_group_ids:
            raise ValueError(f"rule group id already exists: {group_id}")
        name = str(group.get("name", group.get("group_name", default_name))).strip()
        if not name:
            name = default_name
        if len(name) > 200:
            raise ValueError("group name must be 200 characters or fewer")
        enabled = _bool(group.get("enabled", group.get("group_enabled", True)), name="group enabled")
        conditions = group.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise ValueError("rule group must contain at least one condition")
        result = []
        local_rule_ids = set()
        for condition in conditions:
            rule = _condition_to_rule(
                condition,
                kind=kind,
                group_id=group_id,
                group_name=name,
                enabled=enabled,
                regime=regime,
                side=side,
            )
            if rule["id"] in existing_rule_ids or rule["id"] in local_rule_ids:
                raise ValueError(f"condition id already exists: {rule['id']}")
            local_rule_ids.add(rule["id"])
            result.append(rule)
        return result

    def list_groups(self, profile: str, family: str) -> dict[str, Any]:
        profile = _profile(profile)
        family = _family(family)
        kind = FAMILY_TO_KIND[family]
        regime, side = _profile_scope(profile)
        groups = []
        for group_id, rules in self._groups_for_kind(kind):
            first = rules[0]
            if first["regime"] in {"ALL", regime} and first["side"] in {"ALL", side}:
                serialized = self._serialize_group(kind, group_id, rules)
                serialized["scope_exact"] = (
                    first["regime"] == regime and first["side"] == side
                )
                groups.append(serialized)
        return {
            "profile": profile,
            "family": family,
            "groups": groups,
            "total": len(groups),
            "active": sum(group["enabled"] for group in groups),
            "muted": sum(not group["enabled"] for group in groups),
        }

    def workspace(self, profile: str | None = None) -> dict[str, Any]:
        legacy_counts = {
            key: sum(
                1
                for rule in profile_config.entry_rules
                if "_builder_id" not in rule and "_strategy_builtin_rule" not in rule
            )
            for key, profile_config in self._parsed.strategy.profiles.items()
        }
        result: dict[str, Any] = {
            "direction_mode": self.direction_mode,
            "market_permissions": list(self.market_permissions),
            "group_semantics": {
                "conditions_inside_group": "ALL",
                "groups_inside_family": "OR",
            },
            "legacy_native_rule_counts": legacy_counts,
            "warnings": [],
        }
        if any(legacy_counts.values()):
            result["warnings"].append(
                "Legacy low-level native rules are present. High-level group edits preserve them, but they are not shown as Strategy Builder groups."
            )
        if profile is not None:
            profile = _profile(profile)
            result["profile"] = profile
            result["entry_groups"] = self.list_groups(profile, "ENTRY")["groups"]
            result["veto_groups"] = self.list_groups(profile, "VETO")["groups"]
            result["flip_groups"] = self.list_groups(profile, "FLIP")["groups"]
        else:
            result["entry_groups"] = [
                self._serialize_group("REQUIRED", gid, rules)
                for gid, rules in self._groups_for_kind("REQUIRED")
            ]
            result["veto_groups"] = [
                self._serialize_group("VETO", gid, rules)
                for gid, rules in self._groups_for_kind("VETO")
            ]
            result["flip_groups"] = [
                self._serialize_group("FLIP", gid, rules)
                for gid, rules in self._groups_for_kind("FLIP")
            ]
        return result

    def add_group(self, profile: str, family: str, group: dict[str, Any]) -> dict[str, Any]:
        profile = _profile(profile)
        family = _family(family)
        kind = FAMILY_TO_KIND[family]
        number = len(self._groups_for_kind(kind)) + 1
        rules = self._make_group_rules(
            profile=profile,
            family=family,
            group=group,
            default_name=f"{family.title()} Group {number}",
            existing_group_ids=self._known_group_ids(),
            existing_rule_ids=self._known_rule_ids(),
        )
        self.rules[kind] = [*rules, *self.rules[kind]]
        return self._serialize_group(kind, rules[0]["group_id"], rules)

    def set_groups(self, profile: str, family: str, groups: list[dict[str, Any]]) -> dict[str, Any]:
        profile = _profile(profile)
        family = _family(family)
        if not isinstance(groups, list):
            raise ValueError("groups must be a list")
        kind = FAMILY_TO_KIND[family]
        regime, side = _profile_scope(profile)
        preserved = [
            rule
            for rule in self.rules[kind]
            if not (rule["regime"] == regime and rule["side"] == side)
        ]
        preserved_group_ids = {
            rule["group_id"] for rule in preserved
        } | {
            rule["group_id"]
            for other_kind in RULE_KINDS
            if other_kind != kind
            for rule in self.rules[other_kind]
        }
        preserved_rule_ids = {
            rule["id"] for rule in preserved
        } | {
            rule["id"]
            for other_kind in RULE_KINDS
            if other_kind != kind
            for rule in self.rules[other_kind]
        }
        new_rules: list[dict[str, Any]] = []
        used_group_ids = set(preserved_group_ids)
        used_rule_ids = set(preserved_rule_ids)
        for index, group in enumerate(groups, 1):
            built = self._make_group_rules(
                profile=profile,
                family=family,
                group=group,
                default_name=f"{family.title()} Group {index}",
                existing_group_ids=used_group_ids,
                existing_rule_ids=used_rule_ids,
            )
            used_group_ids.add(built[0]["group_id"])
            used_rule_ids.update(rule["id"] for rule in built)
            new_rules.extend(built)
        self.rules[kind] = [*new_rules, *preserved]
        return self.list_groups(profile, family)

    def update_group(self, group_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("group patch must be an object")
        if any(key in patch for key in ("id", "group_id", "family", "scope", "profile")):
            raise ValueError("group id, family, and scope are immutable; create a new group to change them")
        kind, existing_rules = self._group_location(group_id)
        first = existing_rules[0]
        profile = f"{first['regime']}_{first['side']}".lower()
        if first["regime"] == "ALL" or first["side"] == "ALL":
            raise ValueError(
                "Shared-scope GUI groups cannot be edited through a profile-scoped MCP update; replace them in the GUI or create an exact-profile group"
            )
        family = KIND_TO_FAMILY[kind]
        current = self._serialize_group(kind, group_id, existing_rules)
        candidate: dict[str, Any] = {
            "id": group_id,
            "name": patch.get("name", patch.get("group_name", current["name"])),
            "enabled": patch.get("enabled", patch.get("group_enabled", current["enabled"])),
            "match_mode": patch.get("match_mode", "ALL"),
            "conditions": patch.get("conditions", current["conditions"]),
        }
        replacement = self._make_group_rules(
            profile=profile,
            family=family,
            group=candidate,
            default_name=current["name"],
            existing_group_ids=self._known_group_ids() - {group_id},
            existing_rule_ids=self._known_rule_ids(excluding_group=group_id),
            forced_group_id=group_id,
        )
        old_ids = {rule["id"] for rule in existing_rules}
        insert_at = min(
            index for index, rule in enumerate(self.rules[kind]) if rule["id"] in old_ids
        )
        self.rules[kind] = [
            rule for rule in self.rules[kind] if rule["group_id"] != group_id
        ]
        for offset, rule in enumerate(replacement):
            self.rules[kind].insert(insert_at + offset, rule)
        return self._serialize_group(kind, group_id, replacement)

    def delete_group(self, group_id: str) -> dict[str, Any]:
        kind, rules = self._group_location(group_id)
        deleted = self._serialize_group(kind, group_id, rules)
        self.rules[kind] = [
            rule for rule in self.rules[kind] if rule["group_id"] != group_id
        ]
        return deleted

    def set_group_enabled(self, group_id: str, enabled: bool) -> dict[str, Any]:
        kind, rules = self._group_location(group_id)
        value = _bool(enabled, name="group enabled")
        for rule in rules:
            rule["group_enabled"] = value
        return self._serialize_group(kind, group_id, rules)

    def to_config(self) -> dict[str, Any]:
        original_profiles = self._parsed.strategy.profiles
        legacy_native = {
            key: tuple(
                deepcopy(rule)
                for rule in profile.entry_rules
                if "_builder_id" not in rule and "_strategy_builtin_rule" not in rule
            )
            for key, profile in original_profiles.items()
        }
        first_profile = original_profiles[PROFILE_KEYS[0]]
        compiled, _unused_execution = compile_profiles(
            direction_mode=self.direction_mode,
            market_permissions=self.market_permissions,
            required_rules=tuple(self.rules["REQUIRED"]),
            veto_rules=tuple(self.rules["VETO"]),
            flip_rules=tuple(self.rules["FLIP"]),
            rsi_period=first_profile.rsi_period,
            momentum_lookback_hours=first_profile.momentum_lookback_hours,
        )
        rebuilt = {}
        for key in PROFILE_KEYS:
            original = original_profiles[key]
            profile = compiled[key]
            profile = replace(
                profile,
                entry_rules=tuple(profile.entry_rules) + legacy_native[key],
                flip_rule_match_mode=original.flip_rule_match_mode,
                reject_rule_match_mode=original.reject_rule_match_mode,
                rsi_period=original.rsi_period,
                momentum_lookback_hours=original.momentum_lookback_hours,
            )
            rebuilt[key] = asdict(profile)
        result = deepcopy(self._base_config)
        result["strategy"]["profiles"] = rebuilt
        return result
