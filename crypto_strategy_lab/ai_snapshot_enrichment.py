"""Enrich AI direction snapshots with causal higher-timeframe structure."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from crypto_strategy_core.support_resistance_evidence import SR_CONTEXT_FIELDS
from crypto_strategy_lab.ai_decision import _json_safe


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


def enrich_ai_snapshot(engine, i: int, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Add identity, independent HTF S/R and confirmed causal structure."""
    result = dict(snapshot)
    result["symbol"] = snapshot_symbol(engine)
    result["higher_timeframe_support_resistance"] = higher_timeframe_sr_snapshot(
        engine, i
    )
    result["confirmed_market_structure"] = confirmed_market_structure_snapshot(
        engine, i
    )
    return _json_safe(result)
