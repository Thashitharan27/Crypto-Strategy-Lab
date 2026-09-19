"""Enrich AI direction snapshots with causal higher-timeframe structure."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from crypto_strategy_core.support_resistance_evidence import SR_CONTEXT_FIELDS
from crypto_strategy_lab.ai_decision import _json_safe
from crypto_strategy_lab.sr_trade_context import (
    derive_trade_sr_context,
    planned_trade_distances,
)


_HTF_SR_CONTEXTS = (
    ("1h", "support_resistance_1h", "sr_1h"),
    ("4h", "support_resistance_4h", "sr_4h"),
    ("1d", "support_resistance_1d", "sr_1d"),
)


def _prepared_raw(engine, i: int, feature_name: str, column: str):
    reader = getattr(engine, "_prepared_research_raw_value", None)
    if reader is None:
        return None
    try:
        return _json_safe(reader(i, feature_name, column))
    except Exception:
        return None


def _prepared_sr_side(engine, i: int, feature_name: str, prefix: str, side: str):
    values: dict[str, Any] = {}
    present = False
    for field in SR_CONTEXT_FIELDS:
        value = _prepared_raw(
            engine,
            i,
            feature_name,
            f"{prefix}_{side.lower()}_{field}",
        )
        values[field] = value
        if value is not None:
            present = True
    return values if present else None


def higher_timeframe_sr_snapshot(engine, i: int) -> dict[str, Any]:
    """Return each prepared higher-timeframe S/R context independently."""
    result: dict[str, Any] = {}
    for label, feature_name, prefix in _HTF_SR_CONTEXTS:
        long_context = _prepared_sr_side(engine, i, feature_name, prefix, "LONG")
        short_context = _prepared_sr_side(engine, i, feature_name, prefix, "SHORT")
        if long_context is None and short_context is None:
            continue
        result[label] = {
            "long": long_context,
            "short": short_context,
        }
    return result


def _semantic_sr_context(engine, i: int, side: str, raw: dict[str, Any] | None):
    if raw is None:
        return None
    regime_values = getattr(engine, "market_regime_values", ())
    try:
        regime = str(regime_values[i]).upper()
    except (IndexError, TypeError):
        regime = ""
    profile = None
    resolver = getattr(engine, "_ai_profile", None)
    if resolver is not None and regime:
        try:
            profile = resolver(regime, side)
        except Exception:
            profile = None
    try:
        risk_unit = float(engine.risk[i])
    except (AttributeError, IndexError, TypeError, ValueError):
        risk_unit = None
    stop_distance, target_distance = planned_trade_distances(profile, risk_unit)

    config = getattr(engine, "config", None)
    risk_mode = getattr(getattr(config, "risk_mode", None), "value", getattr(config, "risk_mode", ""))
    if str(risk_mode).upper() == "SR_STRUCTURE":
        stop_distance = None
        target_distance = None
    if str(getattr(config, "sr_take_profit_mode", "FIXED_R")).upper() != "FIXED_R":
        target_distance = None

    try:
        strategy_atr = float(engine.atr_values[i])
        reference_price = float(engine.close[i])
    except (AttributeError, IndexError, TypeError, ValueError):
        strategy_atr = None
        reference_price = None
    return derive_trade_sr_context(
        direction=side,
        raw=raw,
        strategy_atr=strategy_atr,
        reference_price=reference_price,
        stop_distance=stop_distance,
        target_distance=target_distance,
    )


def trade_relative_sr_snapshot(engine, i: int, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return one unambiguous S/R contract for LONG and SHORT."""
    raw_htf = higher_timeframe_sr_snapshot(engine, i)
    directional = snapshot.get("directional_context") or {}
    result: dict[str, Any] = {}
    for side in ("LONG", "SHORT"):
        side_context = directional.get(side) or {}
        raw_strategy = side_context.get("support_resistance")
        timeframes = {}
        strategy = _semantic_sr_context(engine, i, side, raw_strategy)
        if strategy is not None:
            timeframes["strategy_tf"] = strategy
        for label in ("1h", "4h", "1d"):
            raw = (raw_htf.get(label) or {}).get(side.lower())
            derived = _semantic_sr_context(engine, i, side, raw)
            if derived is not None:
                timeframes[label] = derived
        result[side.lower()] = {
            "unit_definitions": {
                "selected_tf_atr": "ATR of the selected S/R timeframe.",
                "strategy_tf_atr": "ATR of the strategy/entry timeframe.",
                "room_r": "Distance to opposing zone edge / configured full stop distance.",
                "room_target_multiple": "Distance to opposing zone edge / planned final target distance.",
            },
            "timeframes": {
                label: {
                    key.removeprefix("SR_").lower(): _json_safe(value)
                    for key, value in values.items()
                    if _json_safe(value) is not None
                }
                for label, values in timeframes.items()
            },
        }
    return result


def confirmed_market_structure_snapshot(engine, i: int):
    """Reuse the mature engine's causal confirmed-swing snapshot when available."""
    analyzer = getattr(engine, "_market_structure_snapshot", None)
    if analyzer is None:
        return None
    try:
        return _json_safe(analyzer(i))
    except Exception:
        return None


def snapshot_symbol(engine) -> str | None:
    """Recover the traded symbol without exposing a path or GUI-only request object."""
    config = getattr(engine, "config", None)
    configured = str(getattr(config, "market_symbol", "") or "").strip().upper()
    if configured and configured != "POLICY":
        return configured
    input_csv = str(getattr(config, "input_csv", "") or "").strip()
    if not input_csv:
        return None
    stem = Path(input_csv).stem.upper()
    match = re.match(r"([A-Z]+?)(?:USDT|USD|BTC|ETH)?(?:_|-|$)", stem)
    return match.group(1) if match else stem or None


def _remove_permission_hints(snapshot: dict[str, Any]) -> None:
    """Keep deterministic market permissions out of the model's evidence.

    The model must rate LONG and SHORT from market evidence even if one side is
    disabled by the execution policy. Permission gating remains downstream.
    """
    directional = snapshot.get("directional_context")
    if not isinstance(directional, dict):
        return
    for side in ("LONG", "SHORT"):
        side_context = directional.get(side)
        if not isinstance(side_context, dict):
            continue
        contract = side_context.get("trade_contract")
        if isinstance(contract, dict):
            contract.pop("enabled", None)


def enrich_ai_snapshot(engine, i: int, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Add identity, independent HTF S/R and confirmed causal structure."""
    result = dict(snapshot)
    _remove_permission_hints(result)
    result["symbol"] = snapshot_symbol(engine)
    result["support_resistance_trade_context_v2"] = trade_relative_sr_snapshot(
        engine, i, result
    )
    directional = result.get("directional_context")
    if isinstance(directional, dict):
        for side in ("LONG", "SHORT"):
            side_context = directional.get(side)
            if isinstance(side_context, dict):
                side_context.pop("support_resistance", None)
    result.pop("higher_timeframe_support_resistance", None)
    result["confirmed_market_structure"] = confirmed_market_structure_snapshot(
        engine, i
    )
    return _json_safe(result)
