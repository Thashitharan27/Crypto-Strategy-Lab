"""Deterministic causal candidate selection over immutable research artifacts.

The walk-forward event stream owns chronology and rule versions.  The immutable
reference run owns the historical opportunity/feature stream.  This module joins
those two surfaces without exposing any trade outcome before a decision is frozen.

`get_next_walk_forward_candidate` is deliberately stateful: once the first
qualifying opportunity is found it immediately appends CANDIDATE_CONTEXT_CAPTURED.
A second scan cannot silently jump over that unresolved candidate.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from crypto_strategy_core.candles import directional_di_ratio
from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.data_lake_config import PROFILE_KEYS
from crypto_strategy_lab.rule_native_engine import (
    _RESEARCH_CATEGORICAL_FIELDS,
    _RESEARCH_NUMERIC_FIELDS,
    _SR_CATEGORICAL_FIELDS,
    _SR_NUMERIC_FIELDS,
)
from crypto_strategy_lab.run_manifest import artifact_path, canonical_sha256
from crypto_strategy_lab.walk_forward_materialization import (
    materialize_walk_forward_strategy,
)


CANDIDATE_CONTEXT_CONTRACT = "causal_walk_forward_candidate_context_v1"
MAX_SCAN_ROWS = 250_000

# Engine-computed entry-time columns that are safe to expose.  Full trade rows
# also contain exit/PnL fields, so never return arbitrary trade columns.
_SAFE_TRADE_ENTRY_COLUMNS = (
    "research_sample_id",
    "research_signal_index",
    "research_episode_id",
    "research_episode_entry_number",
    "strategy_profile_key",
    "side",
    "trade_direction",
    "signal_strategy",
    "entry_timing_mode",
    "signal_candle_time",
    "signal_available_at",
    "signal_close_price",
    "entry_time",
    "entry_price",
    "strategy_entry_time",
    "strategy_entry_price",
    "market_regime",
    "market_regime_return",
    "atr_at_entry",
    "atr_pct",
    "entry_atr_pct",
    "adx",
    "plus_di",
    "minus_di",
    "di_spread",
    "di_ratio",
    "directional_di",
    "opposing_di",
    "directional_di_change",
    "opposing_di_change",
    "di_spread_change",
    "di_pressure_state",
    "plus_di_change",
    "minus_di_change",
    "bb_width",
    "bb_width_pct",
    "bb_width_change",
    "bb_width_change_pct",
    "bb_width_entry_5bar_change",
    "bb_width_entry_5bar_change_pct",
    "rsi",
    "entry_rsi",
    "momentum",
    "directional_momentum_return_at_entry",
    "ema_50",
    "ema_100",
    "ema_200",
    "ema_50_distance_atr",
    "ema_100_distance_atr",
    "ema_200_distance_atr",
    "macd_line",
    "macd_signal",
    "macd_histogram",
    "macd_histogram_change",
    "macd_cross_state",
    "macd_zero_state",
    "mean_reversion_state",
    "mean_reversion_motion",
    "mean_reversion_strength_label",
    "mean_reversion_signal",
    "mean_reversion_bb_location",
    "mean_reversion_bb_zscore",
    "mean_reversion_distance_atr",
    "mean_reversion_distance_change_atr",
    "mean_distance_atr",
    "mean_distance_change_atr",
    "entry_close_location",
    "close_location",
    "session_vwap",
)


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        return stamp.isoformat()
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "value") and not isinstance(value, str):
        return _json_safe(value.value)
    return str(value) if not isinstance(value, (dict, list, tuple)) else value


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError(f"{name} is missing")
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp


def _events_for(store: CausalExperimentStore, experiment_id: str) -> list[dict[str, Any]]:
    _value, directory, _manifest, events_path = store._paths(experiment_id)
    store._assert_safe_dir(directory, must_exist=True)
    events = store._read_all_events(events_path)
    store._verify_chain(events)
    return events


def _verify_head(
    store: CausalExperimentStore,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    readback = store.read(experiment_id, recent_events=0)
    if int(readback["sequence"]) != int(expected_sequence):
        raise ValueError(
            "walk-forward experiment changed since it was read; read the verified chain head again"
        )
    if str(readback["state_hash"]) != str(expected_state_hash).strip().lower():
        raise ValueError(
            "walk-forward experiment changed since it was read; read the verified chain head again"
        )
    events = _events_for(store, experiment_id)
    sequence, state_hash = store._verify_chain(events)
    if sequence != int(expected_sequence) or state_hash != str(expected_state_hash).strip().lower():
        raise ValueError("walk-forward event chain changed during candidate selection")
    return readback, events


def _open_candidate(events: list[dict[str, Any]]) -> tuple[str, str] | None:
    ids: list[str] = []
    for event in events:
        candidate_id = str((event.get("payload") or {}).get("candidate_id", "")).strip()
        if candidate_id and candidate_id not in ids:
            ids.append(candidate_id)
    for candidate_id in ids:
        state = CausalExperimentStore._candidate_state(events, candidate_id)
        if state not in {"UNSEEN", "INVALID", "COMPLETE"}:
            return candidate_id, state
    return None


def _seen_candidate_keys(events: list[dict[str, Any]]) -> tuple[set[str], set[tuple[int, str]]]:
    samples: set[str] = set()
    indices: set[tuple[int, str]] = set()
    for event in events:
        payload = event.get("payload") or {}
        candidate_id = str(payload.get("candidate_id", "")).strip()
        if not candidate_id:
            continue
        sample = str(payload.get("reference_sample_id", "")).strip()
        if sample:
            samples.add(sample)
        raw_index = payload.get("research_signal_index")
        side = str(payload.get("source_side", "")).upper()
        try:
            if raw_index is not None and side in {"LONG", "SHORT"}:
                indices.add((int(raw_index), side))
        except (TypeError, ValueError):
            pass
    return samples, indices


def _market_cursor(events: list[dict[str, Any]]) -> pd.Timestamp | None:
    stamps: list[pd.Timestamp] = []
    for event in events:
        value = event.get("effective_market_time")
        if value in (None, ""):
            continue
        try:
            stamps.append(_utc_timestamp(value, "effective_market_time"))
        except (TypeError, ValueError):
            continue
    return max(stamps) if stamps else None


def _last_teacher_time(events: list[dict[str, Any]]) -> pd.Timestamp | None:
    stamps = []
    for event in events:
        if event.get("event_type") != "TEACHER_RESOLVED":
            continue
        value = event.get("effective_market_time")
        if value in (None, ""):
            continue
        stamps.append(_utc_timestamp(value, "teacher effective_market_time"))
    return max(stamps) if stamps else None


def _artifact(manifest: dict[str, Any], run_dir: Path, name: str) -> Path:
    if name not in (manifest.get("artifacts") or {}):
        raise ValueError(f"reference run is missing required artifact: {name}")
    return artifact_path(run_dir, manifest, name, verify=True)


def _sampling_mode(manifest: dict[str, Any]) -> str:
    research = manifest.get("research") or {}
    value = research.get("strategy_research_sampling") or {}
    return str(value.get("mode") or value.get("research_sampling_mode") or "").upper()


def _quoted(path: Path) -> str:
    return str(path).replace("'", "''")


def _columns(connection: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    escaped = _quoted(path)
    rows = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{escaped}')"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _candidate_frame(
    samples_path: Path,
    context_path: Path,
    *,
    cursor: pd.Timestamp | None,
    limit: int,
) -> pd.DataFrame:
    with duckdb.connect(":memory:") as connection:
        sample_columns = _columns(connection, samples_path)
        context_columns = _columns(connection, context_path)
        required_samples = {
            "research_signal_index", "strategy_profile_key", "side", "entry_time"
        }
        required_context = {"strategy_index", "decision_available_at"}
        if required_samples - set(sample_columns):
            raise ValueError(
                "Every Viable Entry artifact is missing candidate identity columns: "
                + ", ".join(sorted(required_samples - set(sample_columns)))
            )
        if required_context - set(context_columns):
            raise ValueError(
                "feature-context artifact is missing causal identity columns: "
                + ", ".join(sorted(required_context - set(context_columns)))
            )
        context_select = []
        for name in context_columns:
            escaped_name = name.replace('"', '""')
            alias = f"__ctx_{name}".replace('"', '')
            context_select.append(f'c."{escaped_name}" AS "{alias}"')
        samples = _quoted(samples_path)
        context = _quoted(context_path)
        where = ""
        params: list[Any] = []
        if cursor is not None:
            # Use >= and skip already-seen identities in Python. This preserves a
            # second opportunity at the same timestamp as the previous event.
            where = "WHERE CAST(t.entry_time AS TIMESTAMPTZ) >= ?"
            params.append(cursor.to_pydatetime())
        sql = f"""
            SELECT t.*, {', '.join(context_select)},
                   prev.adx AS __wf_prev_adx
            FROM read_parquet('{samples}') t
            JOIN read_parquet('{context}') c
              ON CAST(t.research_signal_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)
            LEFT JOIN read_parquet('{context}') prev
              ON CAST(prev.strategy_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)-1
            {where}
            ORDER BY CAST(t.entry_time AS TIMESTAMPTZ),
                     CAST(t.research_signal_index AS BIGINT),
                     UPPER(CAST(t.side AS VARCHAR))
            LIMIT {int(limit)}
        """
        return connection.execute(sql, params).fetchdf()


def _row_maps(row: pd.Series) -> tuple[dict[str, Any], dict[str, Any]]:
    trade: dict[str, Any] = {}
    context: dict[str, Any] = {}
    for name, value in row.items():
        key = str(name)
        if key.startswith("__ctx_"):
            context[key[6:]] = value
        else:
            trade[key] = value
    merged = {**context, **trade}
    return merged, context


def _present(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _category(value: Any) -> str | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)):
        return "TRUE" if bool(value) else "FALSE"
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = str(getattr(value, "value", value)).strip().upper()
    return None if not text or text in {"NAN", "NONE", "<NA>"} else text


def _ema_stack(row: dict[str, Any]) -> str | None:
    e50 = _number(_present(row, "ema_50"))
    e100 = _number(_present(row, "ema_100"))
    e200 = _number(_present(row, "ema_200"))
    if not all(math.isfinite(value) for value in (e50, e100, e200)):
        return None
    if e50 > e100 > e200:
        return "EMA50_GT_EMA100_GT_EMA200"
    if e50 < e100 < e200:
        return "EMA50_LT_EMA100_LT_EMA200"
    return "MIXED"


def _price_vs_ema(row: dict[str, Any]) -> str | None:
    price = _number(_present(row, "signal_close_price", "close"))
    e50 = _number(_present(row, "ema_50"))
    e100 = _number(_present(row, "ema_100"))
    e200 = _number(_present(row, "ema_200"))
    if not all(math.isfinite(value) for value in (price, e50, e100, e200)):
        return None
    if price > max(e50, e100, e200):
        return "ABOVE_ALL"
    if price < min(e50, e100, e200):
        return "BELOW_ALL"
    if price > e50:
        return "ABOVE_EMA50"
    if price > e100:
        return "ABOVE_EMA100"
    if price > e200:
        return "ABOVE_EMA200"
    return "MIXED"


def _sr_prefix(config: dict[str, Any], condition: dict[str, Any]) -> str | None:
    raw = condition.get("sr_timeframe_minutes")
    strategy_minutes = int((config.get("data") or {}).get("strategy_timeframe_minutes", 0))
    configured = int((config.get("features") or {}).get("sr_timeframe_minutes", 0) or 0)
    if raw is None:
        requested = configured or strategy_minutes
    else:
        requested = int(raw)
        if requested == 0:
            requested = strategy_minutes
    if requested == strategy_minutes:
        return "sr_strategy"
    return {60: "sr_1h", 240: "sr_4h", 1440: "sr_1d"}.get(requested)


def _evidence_value(
    row: dict[str, Any],
    *,
    direction: str,
    profile: str,
    condition: dict[str, Any],
    config: dict[str, Any],
) -> Any:
    indicator = str(condition.get("indicator", "")).upper()
    direction = str(direction).upper()

    if indicator == "DI_SPREAD":
        return _present(row, "di_spread")
    if indicator == "DIRECTIONAL_DI":
        return _present(row, "plus_di" if direction == "LONG" else "minus_di")
    if indicator == "DIRECTIONAL_DI_RATIO":
        directional = _number(_present(row, "plus_di" if direction == "LONG" else "minus_di"))
        opposing = _number(_present(row, "minus_di" if direction == "LONG" else "plus_di"))
        if not math.isfinite(directional) or not math.isfinite(opposing):
            return None
        return directional_di_ratio(directional, opposing)
    if indicator == "DI_PRESSURE_STATE":
        return _present(
            row,
            "long_di_pressure_state" if direction == "LONG" else "short_di_pressure_state",
            "di_pressure_state",
        )
    if indicator == "DI_SPREAD_CHANGE":
        return _present(row, "di_pressure_spread_change", "di_spread_change")
    if indicator == "DIRECTIONAL_DI_CHANGE":
        return _present(
            row,
            "long_directional_di_change" if direction == "LONG" else "short_directional_di_change",
            "directional_di_change",
        )
    if indicator == "OPPOSING_DI_CHANGE":
        return _present(
            row,
            "long_opposing_di_change" if direction == "LONG" else "short_opposing_di_change",
            "opposing_di_change",
        )
    if indicator == "ADX":
        return _present(row, "adx")
    if indicator == "ADX_CHANGE":
        current = _number(_present(row, "adx"))
        previous = _number(_present(row, "__wf_prev_adx"))
        return current - previous if math.isfinite(current) and math.isfinite(previous) else None
    if indicator == "ATR_PCT":
        return _present(row, "atr_pct", "entry_atr_pct")
    if indicator in {"EMA_50_DISTANCE_ATR", "EMA_100_DISTANCE_ATR", "EMA_200_DISTANCE_ATR"}:
        return _present(row, indicator.lower())
    if indicator == "EMA_STACK_STATE":
        return _ema_stack(row)
    if indicator == "PRICE_VS_EMA_STACK":
        return _price_vs_ema(row)
    if indicator in {"MACD_LINE", "MACD_SIGNAL", "MACD_HISTOGRAM", "MACD_HISTOGRAM_CHANGE"}:
        return _present(row, indicator.lower())
    if indicator in {"MACD_CROSS_STATE", "MACD_ZERO_STATE"}:
        return _present(row, indicator.lower())
    if indicator == "RSI":
        return _present(row, "rsi", "entry_rsi")
    if indicator == "BB_WIDTH":
        return _present(row, "bb_width")
    if indicator == "CLOSE_LOCATION":
        return _present(row, "close_location", "entry_close_location")
    if indicator == "MOMENTUM":
        raw = _present(row, "momentum", "directional_momentum_return_at_entry")
        if raw is not None:
            return raw
        profile_cfg = ((config.get("strategy") or {}).get("profiles") or {}).get(profile) or {}
        hours = int(profile_cfg.get("momentum_lookback_hours", 24))
        return _present(row, f"momentum_return_{hours}h")
    if indicator == "VWAP_DISTANCE":
        close = _number(_present(row, "signal_close_price", "close"))
        vwap = _number(_present(row, "session_vwap"))
        atr = _number(_present(row, "atr_at_entry", "atr"))
        if not all(math.isfinite(value) for value in (close, vwap, atr)) or atr <= 0:
            return None
        return (close - vwap) / atr if direction == "LONG" else (vwap - close) / atr

    if indicator == "MR_TRADE_STRETCH_ATR":
        value = _number(_present(row, "mean_reversion_distance_atr", "mean_distance_atr"))
        if not math.isfinite(value):
            return None
        return value if direction == "LONG" else -value
    if indicator == "MR_DISTANCE_ATR":
        return _present(row, "mean_reversion_distance_atr", "mean_distance_atr")
    if indicator == "MR_BB_ZSCORE":
        return _present(row, "mean_reversion_bb_zscore")
    if indicator == "MR_DISTANCE_CHANGE_ATR":
        return _present(row, "mean_reversion_distance_change_atr", "mean_distance_change_atr")
    if indicator == "MR_TRADE_ALIGNMENT":
        signal = _category(_present(row, "mean_reversion_signal", "mr_signal"))
        if signal is None:
            return None
        if signal.endswith("_LONG"):
            expected = "LONG"
        elif signal.endswith("_SHORT"):
            expected = "SHORT"
        elif signal == "NEUTRAL":
            return "NEUTRAL"
        else:
            return None
        return "FAVORS_REVERSION" if direction == expected else "AGAINST_REVERSION"
    mr_categories = {
        "MR_MOTION": ("mean_reversion_motion",),
        "MR_BB_LOCATION": ("mean_reversion_bb_location",),
        "MR_SIGNAL": ("mean_reversion_signal", "mr_signal"),
        "MR_STRENGTH": ("mean_reversion_strength_label",),
        "MR_STATE": ("mean_reversion_state",),
    }
    if indicator in mr_categories:
        return _present(row, *mr_categories[indicator])

    if indicator in _SR_CATEGORICAL_FIELDS or indicator in _SR_NUMERIC_FIELDS:
        prefix = _sr_prefix(config, condition)
        if prefix is None:
            return None
        field = _SR_CATEGORICAL_FIELDS.get(indicator) or _SR_NUMERIC_FIELDS.get(indicator)
        return _present(row, f"{prefix}_{direction.lower()}_{field}")

    if indicator in _RESEARCH_NUMERIC_FIELDS:
        _feature, column, scale = _RESEARCH_NUMERIC_FIELDS[indicator]
        raw = _number(_present(row, column))
        return raw * float(scale) if math.isfinite(raw) else None
    if indicator in _RESEARCH_CATEGORICAL_FIELDS:
        _feature, column = _RESEARCH_CATEGORICAL_FIELDS[indicator]
        return _present(row, column)

    # EMA 9/20 signal-specific rules need fields not fully preserved in the
    # immutable feature-context contract (notably volume). Never guess them.
    return None


def _condition_matches(
    row: dict[str, Any],
    *,
    direction: str,
    profile: str,
    condition: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    value = _evidence_value(
        row,
        direction=direction,
        profile=profile,
        condition=condition,
        config=config,
    )
    operator = str(condition.get("condition", "EQUALS")).upper()
    indicator = str(condition.get("indicator", "")).upper()
    detail = {
        "condition_id": condition.get("id"),
        "indicator": indicator,
        "condition": operator,
        "observed": _json_safe(value),
    }
    if value is None:
        detail["matched"] = False
        detail["availability"] = "MISSING_OR_UNSUPPORTED"
        return False, detail

    if operator in {"EQUALS", "NOT_EQUALS"}:
        target = condition.get("value")
        numeric_value = _number(value)
        numeric_target = _number(target)
        if math.isfinite(numeric_value) and math.isfinite(numeric_target) and not isinstance(target, str):
            equals = numeric_value == numeric_target
        else:
            equals = _category(value) == _category(target)
        matched = equals if operator == "EQUALS" else not equals
    else:
        observed = _number(value)
        if not math.isfinite(observed):
            detail["matched"] = False
            detail["availability"] = "NON_NUMERIC"
            return False, detail
        if operator in {"GT", "GTE", "LT", "LTE"}:
            target = _number(condition.get("value"))
            if not math.isfinite(target):
                raise ValueError(f"numeric condition for {indicator} has an invalid threshold")
            matched = {
                "GT": observed > target,
                "GTE": observed >= target,
                "LT": observed < target,
                "LTE": observed <= target,
            }[operator]
        elif operator in {"BETWEEN", "OUTSIDE"}:
            lower = _number(condition.get("minimum"))
            upper = _number(condition.get("maximum"))
            if not math.isfinite(lower) or not math.isfinite(upper):
                raise ValueError(f"range condition for {indicator} has invalid bounds")
            inside = lower <= observed <= upper
            matched = inside if operator == "BETWEEN" else not inside
        else:
            raise ValueError(f"unsupported Strategy Builder condition operator: {operator}")
    detail["matched"] = bool(matched)
    detail["availability"] = "AVAILABLE"
    return bool(matched), detail


def _group_matches(
    row: dict[str, Any],
    *,
    direction: str,
    profile: str,
    group: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    if not bool(group.get("enabled", True)):
        return False, []
    conditions = group.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError(f"rule group {group.get('id')} has no conditions")
    details = []
    matched = True
    for condition in conditions:
        result, detail = _condition_matches(
            row,
            direction=direction,
            profile=profile,
            condition=condition,
            config=config,
        )
        details.append(detail)
        matched = matched and result
    return matched, details


def _rule_decision(
    row: dict[str, Any],
    *,
    profile: str,
    source_side: str,
    groups: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    entry_matches = []
    entry_diagnostics = []
    active_entry_groups = [group for group in groups.get("ENTRY", []) if bool(group.get("enabled", True))]
    for group in active_entry_groups:
        matched, conditions = _group_matches(
            row,
            direction=source_side,
            profile=profile,
            group=group,
            config=config,
        )
        entry_diagnostics.append({"group_id": group.get("id"), "matched": matched, "conditions": conditions})
        if matched:
            entry_matches.append(str(group.get("id")))
    if not active_entry_groups or not entry_matches:
        return {
            "eligible": False,
            "reason": "NO_ENTRY_GROUP_MATCH",
            "matched_entry_groups": [],
            "entry_diagnostics": entry_diagnostics,
        }

    veto_matches = []
    for group in groups.get("VETO", []):
        matched, _details = _group_matches(
            row,
            direction=source_side,
            profile=profile,
            group=group,
            config=config,
        )
        if matched:
            veto_matches.append(str(group.get("id")))
    if veto_matches:
        return {
            "eligible": False,
            "reason": "VETO_GROUP_MATCH",
            "matched_entry_groups": entry_matches,
            "matched_veto_groups": veto_matches,
        }

    flip_matches = []
    for group in groups.get("FLIP", []):
        matched, _details = _group_matches(
            row,
            direction=source_side,
            profile=profile,
            group=group,
            config=config,
        )
        if matched:
            flip_matches.append(str(group.get("id")))
    effective_side = (
        "SHORT" if source_side == "LONG" else "LONG"
    ) if flip_matches else source_side
    return {
        "eligible": True,
        "reason": "ENTRY_MATCHED",
        "matched_entry_groups": entry_matches,
        "matched_veto_groups": [],
        "matched_flip_groups": flip_matches,
        "rule_effective_side": effective_side,
    }


def _safe_context(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    trade = {
        name: _json_safe(row[name])
        for name in _SAFE_TRADE_ENTRY_COLUMNS
        if name in row and _json_safe(row[name]) is not None
    }
    feature = {
        str(name): _json_safe(value)
        for name, value in context.items()
        if _json_safe(value) is not None
    }
    return {
        "trade_entry_context": trade,
        # feature_context is generated from PreparedBacktestFrame and contains
        # only values whose causal availability is validated at candle completion.
        "feature_context": feature,
    }


def _next_teacher_boundary(
    manifest: dict[str, Any],
    run_dir: Path,
    events: list[dict[str, Any]],
    candidate_time: pd.Timestamp,
) -> dict[str, Any] | None:
    """Prevent a candidate scan from stepping past an unresolved reference winner.

    Teacher learning is triggered only when a reference winner resolves. We need
    only its resolution boundary here; detailed teacher review remains a separate
    causal action and this helper does not append or learn anything.
    """
    artifacts = manifest.get("artifacts") or {}
    if "trades" not in artifacts:
        return None
    trades_path = artifact_path(run_dir, manifest, "trades", verify=True)
    last = _last_teacher_time(events)
    where = "pair_net_r > 0"
    params: list[Any] = []
    if last is not None:
        where += " AND CAST(exit_time AS TIMESTAMPTZ) > ?"
        params.append(last.to_pydatetime())
    escaped = _quoted(trades_path)
    with duckdb.connect(":memory:") as connection:
        row = connection.execute(
            f"""
            SELECT pair_id, trade_id, side, strategy_profile_key, entry_time, exit_time
            FROM read_parquet('{escaped}')
            WHERE {where}
            ORDER BY CAST(exit_time AS TIMESTAMPTZ), CAST(pair_id AS BIGINT)
            LIMIT 1
            """,
            params,
        ).fetchone()
    if row is None:
        return None
    exit_time = _utc_timestamp(row[5], "teacher exit_time")
    if exit_time > candidate_time:
        return None
    return {
        "pair_id": _json_safe(row[0]),
        "trade_id": _json_safe(row[1]),
        "side": _json_safe(row[2]),
        "strategy_profile_key": _json_safe(row[3]),
        "entry_time": _json_safe(row[4]),
        "resolution_time": exit_time.isoformat(),
    }


def get_next_walk_forward_candidate(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    max_scan_rows: int = MAX_SCAN_ROWS,
) -> dict[str, Any]:
    """Find and atomically capture the first causally eligible EVE opportunity."""
    if isinstance(max_scan_rows, bool) or not isinstance(max_scan_rows, int):
        raise ValueError("max_scan_rows must be an integer")
    if not 1 <= max_scan_rows <= MAX_SCAN_ROWS:
        raise ValueError(f"max_scan_rows must be between 1 and {MAX_SCAN_ROWS}")

    store = CausalExperimentStore(Path(control.project_root) / "walk_forward_experiments")
    readback, events = _verify_head(
        store, experiment_id, expected_sequence, expected_state_hash
    )
    unresolved = _open_candidate(events)
    if unresolved is not None:
        candidate_id, state = unresolved
        raise ValueError(
            f"candidate {candidate_id} is still {state}; finish or invalidate it before scanning ahead"
        )

    snapshot = materialize_walk_forward_strategy(
        control,
        reports,
        experiment_id=experiment_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
        include_config=True,
    )
    config = deepcopy(snapshot["materialized_config"])
    groups_by_profile = deepcopy(snapshot["groups_by_profile"])

    definition = (readback["manifest"] or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", "")).strip()
    if not reference_run:
        raise ValueError("experiment definition has no reference_run")
    reference_manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)
    if _sampling_mode(reference_manifest) != "EVERY_VIABLE_ENTRY":
        raise ValueError(
            "reference run must contain an EVERY_VIABLE_ENTRY research-sampling artifact for deterministic candidate selection"
        )
    samples_path = _artifact(reference_manifest, run_dir, "research_sampling_trades")
    context_path = _artifact(reference_manifest, run_dir, "feature_context")

    cursor = _market_cursor(events)
    frame = _candidate_frame(
        samples_path,
        context_path,
        cursor=cursor,
        limit=max_scan_rows,
    )
    seen_samples, seen_indices = _seen_candidate_keys(events)
    scanned = 0
    skipped_seen = 0
    skipped_profiles = 0
    rejected_by_rules = 0

    for _, series in frame.iterrows():
        scanned += 1
        row, context = _row_maps(series)
        signal_index = int(row["research_signal_index"])
        source_side = str(row["side"]).upper()
        profile = str(row.get("strategy_profile_key", "")).lower()
        sample_id = str(row.get("research_sample_id", "") or "").strip()
        if (sample_id and sample_id in seen_samples) or (signal_index, source_side) in seen_indices:
            skipped_seen += 1
            continue
        if profile not in PROFILE_KEYS or profile not in groups_by_profile:
            skipped_profiles += 1
            continue
        profile_cfg = ((config.get("strategy") or {}).get("profiles") or {}).get(profile) or {}
        if not bool(profile_cfg.get("enabled", False)):
            skipped_profiles += 1
            continue

        decision = _rule_decision(
            row,
            profile=profile,
            source_side=source_side,
            groups=groups_by_profile[profile],
            config=config,
        )
        if not decision.get("eligible"):
            rejected_by_rules += 1
            continue

        entry_time = _utc_timestamp(row["entry_time"], "candidate entry_time")
        decision_time = _present(context, "decision_available_at") or row.get("signal_available_at") or entry_time
        decision_time = _utc_timestamp(decision_time, "candidate decision_available_at")

        teacher = _next_teacher_boundary(
            reference_manifest,
            run_dir,
            events,
            decision_time,
        )
        if teacher is not None:
            return {
                "contract": CANDIDATE_CONTEXT_CONTRACT,
                "status": "TEACHER_DUE_FIRST",
                "experiment_id": experiment_id,
                "sequence": int(expected_sequence),
                "state_hash": str(expected_state_hash),
                "teacher_boundary": teacher,
                "candidate_not_captured": True,
                "scan": {
                    "rows_scanned": scanned,
                    "skipped_seen": skipped_seen,
                    "skipped_disabled_profiles": skipped_profiles,
                    "rejected_by_current_rules": rejected_by_rules,
                },
            }

        candidate_id = f"{signal_index}-{source_side.lower()}"
        if CausalExperimentStore._candidate_state(events, candidate_id) != "UNSEEN":
            suffix = hashlib.sha256(
                f"{sample_id}:{profile}".encode("utf-8")
            ).hexdigest()[:8]
            candidate_id = f"{signal_index}-{source_side.lower()}-{suffix}"
        safe = _safe_context(row, context)
        context_core = {
            "contract": CANDIDATE_CONTEXT_CONTRACT,
            "experiment_id": experiment_id,
            "experiment_sequence_before_capture": int(expected_sequence),
            "experiment_state_hash_before_capture": str(expected_state_hash),
            "strategy_snapshot_sha256": snapshot["snapshot_sha256"],
            "reference_run": reference_run,
            "reference_sample_id": sample_id or None,
            "research_signal_index": signal_index,
            "candidate_id": candidate_id,
            "strategy_profile_key": profile,
            "source_side": source_side,
            "rule_effective_side": decision["rule_effective_side"],
            "entry_time": entry_time.isoformat(),
            "decision_available_at": decision_time.isoformat(),
            "matched_entry_groups": decision["matched_entry_groups"],
            "matched_veto_groups": decision.get("matched_veto_groups", []),
            "matched_flip_groups": decision.get("matched_flip_groups", []),
            "context": safe,
        }
        feature_hash = canonical_sha256(context_core)
        token_payload = {
            "experiment_id": experiment_id,
            "sequence": int(expected_sequence),
            "state_hash": str(expected_state_hash),
            "snapshot": snapshot["snapshot_sha256"],
            "candidate_id": candidate_id,
            "reference_sample_id": sample_id or None,
            "research_signal_index": signal_index,
            "feature_hash": feature_hash,
        }
        candidate_token = canonical_sha256(token_payload)
        payload = {
            **context_core,
            "feature_hash": feature_hash,
            "candidate_token": candidate_token,
        }
        appended = store.append_event(
            experiment_id,
            "CANDIDATE_CONTEXT_CAPTURED",
            payload,
            operation_id,
            int(expected_sequence),
            str(expected_state_hash),
            effective_market_time=entry_time.isoformat(),
            source="DETERMINISTIC_CANDIDATE_ENGINE",
        )
        return {
            "contract": CANDIDATE_CONTEXT_CONTRACT,
            "status": "CANDIDATE_CAPTURED",
            "experiment_id": experiment_id,
            "sequence": appended["sequence"],
            "state_hash": appended["state_hash"],
            "previous_state_hash": str(expected_state_hash),
            "candidate": payload,
            "scan": {
                "rows_scanned": scanned,
                "skipped_seen": skipped_seen,
                "skipped_disabled_profiles": skipped_profiles,
                "rejected_by_current_rules": rejected_by_rules,
            },
            "next_required_event": "DECISION_FROZEN",
            "decision_state_hash": appended["state_hash"],
            "outcome_exposed": False,
        }

    return {
        "contract": CANDIDATE_CONTEXT_CONTRACT,
        "status": "NO_ELIGIBLE_CANDIDATE_IN_SCAN",
        "experiment_id": experiment_id,
        "sequence": int(expected_sequence),
        "state_hash": str(expected_state_hash),
        "scan": {
            "rows_scanned": scanned,
            "skipped_seen": skipped_seen,
            "skipped_disabled_profiles": skipped_profiles,
            "rejected_by_current_rules": rejected_by_rules,
            "max_scan_rows": max_scan_rows,
        },
        "outcome_exposed": False,
    }
