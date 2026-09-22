"""Deterministic causal candidate selection over immutable research artifacts.

The event stream owns chronology and rule versions. The immutable reference run
owns the historical opportunity and entry-time feature stream. This module joins
them without returning exit/PnL/result fields before a decision is frozen.

Finding a candidate is stateful: the first qualifying opportunity is immediately
recorded as ``CANDIDATE_CONTEXT_CAPTURED``. A later scan therefore cannot skip an
unresolved candidate or silently apply a newer rule state to it.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from crypto_strategy_core.candles import directional_di_ratio
from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.data_lake_config import PROFILE_KEYS
from crypto_strategy_lab.mtf_sr_reaction import (
    MTF_SR_DERIVED_RULE_INDICATORS,
    PRICE_ACTION_RULE_INDICATORS,
)
from crypto_strategy_lab.rule_native_engine import (
    _RESEARCH_CATEGORICAL_FIELDS,
    _RESEARCH_NUMERIC_FIELDS,
    _SR_CATEGORICAL_FIELDS,
    _SR_NUMERIC_FIELDS,
)
from crypto_strategy_lab.run_manifest import artifact_path, canonical_sha256
from crypto_strategy_lab.sr_trade_context import (
    RAW_SR_FIELDS,
    SR_TRADE_RULE_INDICATORS,
    derive_trade_sr_context,
    planned_trade_distances,
)
from crypto_strategy_lab.strategy_rule_model import CATEGORICAL_RULE_PRESETS
from crypto_strategy_lab.walk_forward_materialization import materialize_walk_forward_strategy


CANDIDATE_CONTEXT_CONTRACT = "causal_walk_forward_candidate_context_v1"
MAX_SCAN_ROWS = 250_000

# Engine-computed values that are known at entry and are useful to ChatGPT's
# frozen directional judgment. Never return arbitrary columns from the trade row:
# the same row also contains exit, P&L and result information.
_SAFE_TRADE_ENTRY_COLUMNS = (
    "research_sample_id", "research_signal_index", "research_episode_id",
    "research_episode_entry_number", "strategy_profile_key", "side",
    "walk_forward_candidate_id", "walk_forward_candidate_source",
    "walk_forward_source_side", "walk_forward_source_profile_key",
    "trade_direction", "signal_strategy", "entry_timing_mode",
    "signal_candle_time", "signal_available_at", "signal_close_price",
    "entry_time", "entry_price", "strategy_entry_time", "strategy_entry_price",
    "market_regime", "market_regime_return", "atr_at_entry", "atr_pct",
    "entry_atr_pct", "adx", "plus_di", "minus_di", "di_spread", "di_ratio",
    "directional_di", "opposing_di", "directional_di_change",
    "opposing_di_change", "di_spread_change", "di_pressure_state",
    "plus_di_change", "minus_di_change", "bb_width", "bb_width_pct",
    "bb_width_change", "bb_width_change_pct", "bb_width_entry_5bar_change",
    "bb_width_entry_5bar_change_pct", "rsi", "entry_rsi", "momentum",
    "directional_momentum_return_at_entry", "ema_50", "ema_100", "ema_200",
    "ema_50_distance_atr", "ema_100_distance_atr", "ema_200_distance_atr",
    "macd_line", "macd_signal", "macd_histogram", "macd_histogram_change",
    "macd_cross_state", "macd_zero_state", "mean_reversion_state",
    "mean_reversion_motion", "mean_reversion_strength_label",
    "mean_reversion_signal", "mean_reversion_bb_location",
    "mean_reversion_bb_zscore", "mean_reversion_distance_atr",
    "mean_reversion_distance_change_atr", "mean_distance_atr",
    "mean_distance_change_atr", "entry_close_location", "close_location",
    "session_vwap",
)

_MTF_PRICE_ACTION_FIELDS = {
    "CANDLE_BODY_ATR": "body_atr",
    "CANDLE_RANGE_ATR": "range_atr",
    "BODY_TO_RANGE_RATIO": "body_to_range_ratio",
    "LOWER_WICK_RATIO": "lower_wick_ratio",
    "UPPER_WICK_RATIO": "upper_wick_ratio",
    "RANGE_CONTRACTION_RATIO": "range_contraction_ratio",
    "BODY_CONTRACTION_RATIO": "body_contraction_ratio",
    "CANDLE_CLOSE_LOCATION": "close_location",
    "BULLISH_ENGULFING": "bullish_engulfing",
    "BEARISH_ENGULFING": "bearish_engulfing",
    "BULLISH_PIN_BAR": "bullish_pin_bar",
    "BEARISH_PIN_BAR": "bearish_pin_bar",
    "BULLISH_REVERSAL_TRIGGER": "bullish_reversal_trigger",
    "BEARISH_REVERSAL_TRIGGER": "bearish_reversal_trigger",
}
_MTF_SR_DERIVED_FIELDS = {
    "SR_APPROACH_MOMENTUM_STATE": "sr_approach_momentum_state",
    "SR_ROLE_REVERSAL_STATE": "sr_role_reversal_state",
    "SR_ZONE_PENETRATION_ATR": "sr_zone_penetration_atr",
    "SR_ZONE_REJECTION_ATR": "sr_zone_rejection_atr",
    "SR_BREAKOUT_BODY_ATR": "sr_breakout_body_atr",
    "SR_BREAKOUT_CLOSE_BEYOND_ZONE_ATR": "sr_breakout_close_beyond_zone_atr",
}
_MTF_LABELS = ("strategy", "1h", "4h", "1d")
_ICHIMOKU_CONTEXT_CONTRACT = "ichimoku_trade_context_v1"
_ICHIMOKU_SUMMARY_FIELDS = (
    "price_vs_cloud",
    "tk_state",
    "tk_cross",
    "tk_spread_atr",
    "tenkan_distance_atr",
    "kijun_distance_atr",
    "kijun_slope_atr",
    "kijun_flat_bars",
    "current_cloud_state",
    "future_cloud_state",
    "cloud_thickness_atr",
    "future_cloud_thickness_atr",
    "kumo_twist",
    "chikou_vs_price",
    "cloud_distance_atr",
)
_SAFE_TRADE_ENTRY_COLUMNS = (
    *_SAFE_TRADE_ENTRY_COLUMNS,
    *(
        f"mtf_{label}_{field}"
        for label in _MTF_LABELS
        for field in _MTF_PRICE_ACTION_FIELDS.values()
    ),
    *(
        f"mtf_{label}_{side}_{field}"
        for label in _MTF_LABELS
        for side in ("long", "short")
        for field in _MTF_SR_DERIVED_FIELDS.values()
    ),
)

_DIRECT_NUMERIC = {
    "DI_SPREAD": ("di_spread",),
    "ADX": ("adx",),
    "ATR_PCT": ("atr_pct", "entry_atr_pct"),
    "EMA_50_DISTANCE_ATR": ("ema_50_distance_atr",),
    "EMA_100_DISTANCE_ATR": ("ema_100_distance_atr",),
    "EMA_200_DISTANCE_ATR": ("ema_200_distance_atr",),
    "MACD_LINE": ("macd_line",),
    "MACD_SIGNAL": ("macd_signal",),
    "MACD_HISTOGRAM": ("macd_histogram",),
    "MACD_HISTOGRAM_CHANGE": ("macd_histogram_change",),
    "RSI": ("rsi", "entry_rsi"),
    "BB_WIDTH": ("bb_width",),
    "CLOSE_LOCATION": ("close_location", "entry_close_location"),
    "MR_DISTANCE_ATR": ("mean_reversion_distance_atr", "mean_distance_atr"),
    "MR_BB_ZSCORE": ("mean_reversion_bb_zscore",),
    "MR_DISTANCE_CHANGE_ATR": (
        "mean_reversion_distance_change_atr", "mean_distance_change_atr"
    ),
}

_DIRECT_CATEGORICAL = {
    "MACD_CROSS_STATE": ("macd_cross_state",),
    "MACD_ZERO_STATE": ("macd_zero_state",),
    "MR_MOTION": ("mean_reversion_motion",),
    "MR_BB_LOCATION": ("mean_reversion_bb_location",),
    "MR_SIGNAL": ("mean_reversion_signal", "mr_signal"),
    "MR_STRENGTH": ("mean_reversion_strength_label",),
    "MR_STATE": ("mean_reversion_state",),
}


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
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        return stamp.isoformat()
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "value") and not isinstance(value, str):
        return _json_safe(value.value)
    return value if isinstance(value, (dict, list, tuple)) else str(value)


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError(f"{name} is missing")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _events(store: CausalExperimentStore, experiment_id: str) -> list[dict[str, Any]]:
    _value, directory, _manifest, events_path = store._paths(experiment_id)
    store._assert_safe_dir(directory, must_exist=True)
    rows = store._read_all_events(events_path)
    store._verify_chain(rows)
    return rows


def _verified_head(
    store: CausalExperimentStore,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    readback = store.read(experiment_id, recent_events=0)
    wanted_hash = str(expected_state_hash).strip().lower()
    if int(readback["sequence"]) != int(expected_sequence) or readback["state_hash"] != wanted_hash:
        raise ValueError(
            "walk-forward experiment changed since it was read; read the verified chain head again"
        )
    rows = _events(store, experiment_id)
    sequence, state_hash = store._verify_chain(rows)
    if sequence != int(expected_sequence) or state_hash != wanted_hash:
        raise ValueError("walk-forward event chain changed during candidate selection")
    return readback, rows


def _existing_operation(events: list[dict[str, Any]], operation_id: str) -> dict[str, Any] | None:
    event = CausalExperimentStore._find_operation(events, str(operation_id))
    if event is None:
        return None
    if event.get("event_type") != "CANDIDATE_CONTEXT_CAPTURED" or event.get("source") != "DETERMINISTIC_CANDIDATE_ENGINE":
        raise ValueError("operation_id was already used for a different causal mutation")
    return event


def _open_candidate(events: list[dict[str, Any]]) -> tuple[str, str] | None:
    candidate_ids: list[str] = []
    for event in events:
        candidate_id = str((event.get("payload") or {}).get("candidate_id", "")).strip()
        if candidate_id and candidate_id not in candidate_ids:
            candidate_ids.append(candidate_id)
    for candidate_id in candidate_ids:
        state = CausalExperimentStore._candidate_state(events, candidate_id)
        if state not in {"UNSEEN", "INVALID", "COMPLETE"}:
            return candidate_id, state
    return None


def _seen_keys(events: list[dict[str, Any]]) -> tuple[set[str], set[tuple[int, str]]]:
    samples: set[str] = set()
    identities: set[tuple[int, str]] = set()
    for event in events:
        payload = event.get("payload") or {}
        if not str(payload.get("candidate_id", "")).strip():
            continue
        sample_id = str(payload.get("reference_sample_id", "")).strip()
        if sample_id:
            samples.add(sample_id)
        try:
            index = int(payload.get("research_signal_index"))
        except (TypeError, ValueError):
            continue
        side = str(payload.get("source_side", "")).upper()
        if side in {"LONG", "SHORT"}:
            identities.add((index, side))
    return samples, identities


def _max_event_time(events: list[dict[str, Any]]) -> pd.Timestamp | None:
    values = []
    for event in events:
        raw = event.get("effective_market_time")
        if raw not in (None, ""):
            values.append(_utc_timestamp(raw, "effective_market_time"))
    return max(values) if values else None


def _last_teacher_time(events: list[dict[str, Any]]) -> pd.Timestamp | None:
    values = []
    for event in events:
        if event.get("event_type") != "TEACHER_RESOLVED":
            continue
        raw = event.get("effective_market_time")
        if raw not in (None, ""):
            values.append(_utc_timestamp(raw, "teacher effective_market_time"))
    return max(values) if values else None


def _artifact(manifest: dict[str, Any], run_dir: Path, name: str) -> Path:
    if name not in (manifest.get("artifacts") or {}):
        raise ValueError(f"reference run is missing required artifact: {name}")
    return artifact_path(run_dir, manifest, name, verify=True)


def _sampling_mode(manifest: dict[str, Any]) -> str:
    sampling = ((manifest.get("research") or {}).get("strategy_research_sampling") or {})
    return str(sampling.get("mode") or sampling.get("research_sampling_mode") or "").upper()


def _quote(path: Path) -> str:
    return str(path).replace("'", "''")


def _columns(connection: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    rows = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{_quote(path)}')"
    ).fetchall()
    return [str(row[0]) for row in rows]


_SCAN_IDENTITY_COLUMNS = frozenset({
    "research_sample_id",
    "research_signal_index",
    "strategy_profile_key",
    "side",
    "entry_time",
    "signal_available_at",
    "walk_forward_candidate_id",
    "walk_forward_candidate_source",
    "strategy_index",
    "decision_available_at",
})


def _condition_required_columns(
    condition: dict[str, Any],
    profile: str,
    config: dict[str, Any],
) -> set[str]:
    """Return the immutable entry-time columns needed to evaluate one rule."""
    indicator = str(condition.get("indicator", "")).upper()
    columns: set[str] = set()

    if indicator in _DIRECT_NUMERIC:
        columns.update(_DIRECT_NUMERIC[indicator])
    elif indicator in _DIRECT_CATEGORICAL:
        columns.update(_DIRECT_CATEGORICAL[indicator])
    elif indicator in PRICE_ACTION_RULE_INDICATORS:
        label = _mtf_label(config, condition)
        field = _MTF_PRICE_ACTION_FIELDS.get(indicator)
        if label and field:
            columns.add(f"mtf_{label}_{field}")
    elif indicator in MTF_SR_DERIVED_RULE_INDICATORS:
        label = _mtf_label(config, condition)
        field = _MTF_SR_DERIVED_FIELDS.get(indicator)
        if label and field:
            columns.update(
                f"mtf_{label}_{side}_{field}" for side in ("long", "short")
            )
    elif indicator in {"DIRECTIONAL_DI", "DIRECTIONAL_DI_RATIO"}:
        columns.update({"plus_di", "minus_di"})
    elif indicator == "DI_PRESSURE_STATE":
        columns.update({
            "long_di_pressure_state",
            "short_di_pressure_state",
            "di_pressure_state",
        })
    elif indicator == "DI_SPREAD_CHANGE":
        columns.update({"di_pressure_spread_change", "di_spread_change"})
    elif indicator == "DIRECTIONAL_DI_CHANGE":
        columns.update({
            "long_directional_di_change",
            "short_directional_di_change",
            "directional_di_change",
        })
    elif indicator == "OPPOSING_DI_CHANGE":
        columns.update({
            "long_opposing_di_change",
            "short_opposing_di_change",
            "opposing_di_change",
        })
    elif indicator == "ADX_CHANGE":
        columns.update({"adx", "__wf_prev_adx"})
    elif indicator == "EMA_STACK_STATE":
        columns.update({"ema_50", "ema_100", "ema_200"})
    elif indicator == "PRICE_VS_EMA_STACK":
        columns.update({
            "signal_close_price", "close", "ema_50", "ema_100", "ema_200",
        })
    elif indicator == "MOMENTUM":
        columns.update({"momentum", "directional_momentum_return_at_entry"})
        profile_cfg = (
            ((config.get("strategy") or {}).get("profiles") or {}).get(profile)
            or {}
        )
        hours = int(profile_cfg.get("momentum_lookback_hours", 24))
        columns.add(f"momentum_return_{hours}h")
    elif indicator == "VWAP_DISTANCE":
        columns.update({
            "signal_close_price", "close", "session_vwap", "atr_at_entry", "atr",
        })
    elif indicator == "MR_TRADE_STRETCH_ATR":
        columns.update({"mean_reversion_distance_atr", "mean_distance_atr"})
    elif indicator == "MR_TRADE_ALIGNMENT":
        columns.update({"mean_reversion_signal", "mr_signal"})
    elif indicator in SR_TRADE_RULE_INDICATORS:
        prefix = _sr_prefix(config, condition)
        if prefix:
            for side in ("long", "short"):
                columns.update(f"{prefix}_{side}_{field}" for field in RAW_SR_FIELDS)
        columns.update({
            "atr",
            "atr_at_entry",
            "signal_close_price",
            "close",
            "strategy_entry_price",
        })
    elif indicator in _SR_CATEGORICAL_FIELDS or indicator in _SR_NUMERIC_FIELDS:
        prefix = _sr_prefix(config, condition)
        field = _SR_CATEGORICAL_FIELDS.get(indicator) or _SR_NUMERIC_FIELDS.get(indicator)
        if prefix and field:
            columns.update(
                f"{prefix}_{side}_{field}" for side in ("long", "short")
            )
    elif indicator in _RESEARCH_NUMERIC_FIELDS:
        _feature, column, _scale = _RESEARCH_NUMERIC_FIELDS[indicator]
        columns.add(column)
    elif indicator in _RESEARCH_CATEGORICAL_FIELDS:
        _feature, column = _RESEARCH_CATEGORICAL_FIELDS[indicator]
        columns.add(column)

    return columns


def _rule_scan_columns(
    groups_by_profile: dict[str, dict[str, list[dict[str, Any]]]],
    config: dict[str, Any],
) -> set[str]:
    """Build a minimal safe projection for deterministic rule scanning."""
    columns = set(_SCAN_IDENTITY_COLUMNS)
    for profile, families in groups_by_profile.items():
        if not isinstance(families, dict):
            continue
        for family in ("ENTRY", "VETO", "FLIP"):
            for group in families.get(family, []) or []:
                if not bool(group.get("enabled", True)):
                    continue
                for condition in group.get("conditions") or []:
                    if isinstance(condition, dict):
                        columns.update(
                            _condition_required_columns(condition, profile, config)
                        )
    return columns


def _projection_parts(
    sample_columns: list[str],
    context_columns: list[str],
    required_columns: set[str] | None,
) -> tuple[list[str], list[str], bool]:
    """Return sample/context SELECT expressions and whether previous ADX is needed."""
    if required_columns is None:
        sample_select = ["t.*"]
        context_names = list(context_columns)
        needs_prev_adx = True
    else:
        requested = set(required_columns) | set(_SCAN_IDENTITY_COLUMNS)
        sample_names = [name for name in sample_columns if name in requested]
        context_names = [name for name in context_columns if name in requested]
        sample_select = []
        for name in sample_names:
            escaped = name.replace('"', '""')
            sample_select.append(f't."{escaped}"')
        needs_prev_adx = "__wf_prev_adx" in requested

    context_select = []
    for name in context_names:
        escaped = name.replace('"', '""')
        alias = ("__ctx_" + name).replace('"', "")
        context_select.append(f'c."{escaped}" AS "{alias}"')
    return sample_select, context_select, needs_prev_adx


def _candidate_rows(
    samples_path: Path,
    context_path: Path,
    cursor: pd.Timestamp | None,
    limit: int,
    required_columns: set[str] | None = None,
) -> pd.DataFrame:
    with duckdb.connect(":memory:") as connection:
        sample_columns = _columns(connection, samples_path)
        context_columns = _columns(connection, context_path)
        required_samples = {
            "research_signal_index", "strategy_profile_key", "side", "entry_time",
            "walk_forward_candidate_id", "walk_forward_candidate_source",
        }
        required_context = {"strategy_index", "decision_available_at"}
        missing_samples = required_samples - set(sample_columns)
        missing_context = required_context - set(context_columns)
        if missing_samples:
            raise ValueError(
                "Walk Forward paired artifact is missing candidate identity columns: "
                + ", ".join(sorted(missing_samples))
            )
        if missing_context:
            raise ValueError(
                "feature-context artifact is missing causal identity columns: "
                + ", ".join(sorted(missing_context))
            )

        sample_select, context_select, needs_prev_adx = _projection_parts(
            sample_columns, context_columns, required_columns
        )
        select_items = [*sample_select, *context_select]
        if needs_prev_adx:
            select_items.append("prev.adx AS __wf_prev_adx")

        conditions = [
            "COALESCE(CAST(t.walk_forward_candidate_source AS BOOLEAN), FALSE)"
        ]
        params: list[Any] = []
        if cursor is not None:
            # Candidate chronology is based on when the decision is actually
            # available, not on the historical entry timestamp. A teacher can
            # resolve after entry_time but before decision_available_at; using
            # entry_time here would permanently skip that still-unseen
            # prospective opportunity after the teacher event advances time.
            #
            # >= is intentional. Seen identities are removed later, preserving a
            # second opportunity at the same decision timestamp as the previous
            # event.
            conditions.append("CAST(c.decision_available_at AS TIMESTAMPTZ) >= ?")
            params.append(cursor.to_pydatetime())
        where = "WHERE " + " AND ".join(conditions)

        prev_join = ""
        if needs_prev_adx:
            prev_join = f"""
            LEFT JOIN read_parquet('{_quote(context_path)}') prev
              ON CAST(prev.strategy_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)-1
            """

        sql = f"""
            SELECT {', '.join(select_items)}
            FROM read_parquet('{_quote(samples_path)}') t
            JOIN read_parquet('{_quote(context_path)}') c
              ON CAST(t.research_signal_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)
            {prev_join}
            {where}
            ORDER BY CAST(c.decision_available_at AS TIMESTAMPTZ),
                     CAST(t.entry_time AS TIMESTAMPTZ),
                     CAST(t.research_signal_index AS BIGINT),
                     UPPER(CAST(t.side AS VARCHAR))
            LIMIT {int(limit)}
        """
        return connection.execute(sql, params).fetchdf()


def _candidate_detail_row(
    samples_path: Path,
    context_path: Path,
    research_signal_index: int,
    side: str,
) -> pd.Series:
    """Hydrate complete entry-time context only after a projected row matches."""
    with duckdb.connect(":memory:") as connection:
        context_columns = _columns(connection, context_path)
        context_select = []
        for name in context_columns:
            escaped = name.replace('"', '""')
            alias = ("__ctx_" + name).replace('"', "")
            context_select.append(f'c."{escaped}" AS "{alias}"')
        rows = connection.execute(
            f"""
            SELECT t.*, {', '.join(context_select)}, prev.adx AS __wf_prev_adx
            FROM read_parquet('{_quote(samples_path)}') t
            JOIN read_parquet('{_quote(context_path)}') c
              ON CAST(t.research_signal_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)
            LEFT JOIN read_parquet('{_quote(context_path)}') prev
              ON CAST(prev.strategy_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)-1
            WHERE COALESCE(CAST(t.walk_forward_candidate_source AS BOOLEAN), FALSE)
              AND CAST(t.research_signal_index AS BIGINT)=?
              AND UPPER(CAST(t.side AS VARCHAR))=?
            LIMIT 2
            """,
            [int(research_signal_index), str(side).upper()],
        ).fetchdf()
    if len(rows) != 1:
        raise ValueError(
            "walk-forward candidate detail lookup did not resolve exactly one source row "
            f"for signal {int(research_signal_index)} {str(side).upper()}"
        )
    return rows.iloc[0]


def _row_maps(series: pd.Series) -> tuple[dict[str, Any], dict[str, Any]]:
    trade: dict[str, Any] = {}
    context: dict[str, Any] = {}
    for raw_name, value in series.items():
        name = str(raw_name)
        if name.startswith("__ctx_"):
            context[name[6:]] = value
        else:
            trade[name] = value
    return {**context, **trade}, context


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
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


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
    values = [_number(_present(row, name)) for name in ("ema_50", "ema_100", "ema_200")]
    if not all(math.isfinite(value) for value in values):
        return None
    e50, e100, e200 = values
    if e50 > e100 > e200:
        return "BULLISH_STACK"
    if e50 < e100 < e200:
        return "BEARISH_STACK"
    return "MIXED"


def _price_vs_ema(row: dict[str, Any]) -> str | None:
    price = _number(_present(row, "signal_close_price", "close"))
    emas = [_number(_present(row, name)) for name in ("ema_50", "ema_100", "ema_200")]
    if not math.isfinite(price) or not all(math.isfinite(value) for value in emas):
        return None
    if price > max(emas):
        return "ABOVE_ALL_EMAS"
    if price < min(emas):
        return "BELOW_ALL_EMAS"
    return "AMONG_EMAS"


def _sr_prefix(config: dict[str, Any], condition: dict[str, Any]) -> str | None:
    strategy_minutes = int((config.get("data") or {}).get("strategy_timeframe_minutes", 0))
    configured = int((config.get("features") or {}).get("sr_timeframe_minutes", 0) or 0)
    raw = condition.get("sr_timeframe_minutes")
    requested = configured or strategy_minutes if raw is None else int(raw) or strategy_minutes
    if requested == strategy_minutes:
        return "sr_strategy"
    return {60: "sr_1h", 240: "sr_4h", 1440: "sr_1d"}.get(requested)


def _mtf_label(config: dict[str, Any], condition: dict[str, Any]) -> str | None:
    strategy_minutes = int((config.get("data") or {}).get("strategy_timeframe_minutes", 0))
    raw = condition.get("sr_timeframe_minutes")
    requested = strategy_minutes if raw in (None, "", 0, "0") else int(raw)
    if requested == strategy_minutes:
        return "strategy"
    return {60: "1h", 240: "4h", 1440: "1d"}.get(requested)


def _wf_profile_contract(config: dict[str, Any], profile: str) -> dict[str, Any]:
    execution = config.get("execution") or {}
    profiles = execution.get("profiles") or {}
    value = profiles.get(profile) or {}
    return value if isinstance(value, dict) else {}


def _wf_risk_unit(row: dict[str, Any], config: dict[str, Any]) -> float:
    execution = config.get("execution") or {}
    mode = str(execution.get("risk_mode", "ATR")).upper()
    close = _number(_present(row, "signal_close_price", "close", "strategy_entry_price"))
    atr = _number(_present(row, "atr", "atr_at_entry"))
    if mode == "FIXED":
        return _number(execution.get("fixed_r"))
    if mode == "PERCENT":
        percent = _number(execution.get("percent_r"))
        return close * percent if math.isfinite(close) and math.isfinite(percent) else math.nan
    multiplier = _number(execution.get("atr_multiplier", 1.0))
    return atr * multiplier if math.isfinite(atr) and math.isfinite(multiplier) else math.nan


def _wf_trade_relative_sr(
    row: dict[str, Any],
    direction: str,
    profile: str,
    condition: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    prefix = _sr_prefix(config, condition)
    if prefix is None:
        return None
    side = str(direction).lower()
    raw = {
        field: _present(row, f"{prefix}_{side}_{field}")
        for field in RAW_SR_FIELDS
    }
    strategy_atr = _number(_present(row, "atr", "atr_at_entry"))
    reference_price = _number(
        _present(row, "signal_close_price", "close", "strategy_entry_price")
    )
    risk_unit = _wf_risk_unit(row, config)
    stop_distance, target_distance = planned_trade_distances(
        _wf_profile_contract(config, profile), risk_unit
    )
    execution = config.get("execution") or {}
    if str(execution.get("risk_mode", "ATR")).upper() == "SR_STRUCTURE":
        stop_distance = None
        target_distance = None
    if str(execution.get("sr_take_profit_mode", "FIXED_R")).upper() != "FIXED_R":
        target_distance = None
    return derive_trade_sr_context(
        direction=direction,
        raw=raw,
        strategy_atr=strategy_atr,
        reference_price=reference_price,
        stop_distance=stop_distance,
        target_distance=target_distance,
    )


def _evidence(
    row: dict[str, Any],
    direction: str,
    profile: str,
    condition: dict[str, Any],
    config: dict[str, Any],
) -> Any:
    indicator = str(condition.get("indicator", "")).upper()
    direction = str(direction).upper()
    if indicator in _DIRECT_NUMERIC:
        return _present(row, *_DIRECT_NUMERIC[indicator])
    if indicator in _DIRECT_CATEGORICAL:
        return _present(row, *_DIRECT_CATEGORICAL[indicator])
    if indicator in PRICE_ACTION_RULE_INDICATORS:
        label = _mtf_label(config, condition)
        field = _MTF_PRICE_ACTION_FIELDS.get(indicator)
        return _present(row, f"mtf_{label}_{field}") if label and field else None
    if indicator in MTF_SR_DERIVED_RULE_INDICATORS:
        label = _mtf_label(config, condition)
        field = _MTF_SR_DERIVED_FIELDS.get(indicator)
        return _present(row, f"mtf_{label}_{direction.lower()}_{field}") if label and field else None
    if indicator == "DIRECTIONAL_DI":
        return _present(row, "plus_di" if direction == "LONG" else "minus_di")
    if indicator == "DIRECTIONAL_DI_RATIO":
        directional = _number(_present(row, "plus_di" if direction == "LONG" else "minus_di"))
        opposing = _number(_present(row, "minus_di" if direction == "LONG" else "plus_di"))
        return directional_di_ratio(directional, opposing) if math.isfinite(directional) and math.isfinite(opposing) else None
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
    if indicator == "ADX_CHANGE":
        current = _number(_present(row, "adx"))
        previous = _number(_present(row, "__wf_prev_adx"))
        return current - previous if math.isfinite(current) and math.isfinite(previous) else None
    if indicator == "EMA_STACK_STATE":
        return _ema_stack(row)
    if indicator == "PRICE_VS_EMA_STACK":
        return _price_vs_ema(row)
    if indicator == "MOMENTUM":
        direct = _present(row, "momentum", "directional_momentum_return_at_entry")
        if direct is not None:
            return direct
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
    if indicator in SR_TRADE_RULE_INDICATORS:
        derived = _wf_trade_relative_sr(row, direction, profile, condition, config)
        return None if derived is None else derived.get(indicator)
    if indicator in _SR_CATEGORICAL_FIELDS or indicator in _SR_NUMERIC_FIELDS:
        prefix = _sr_prefix(config, condition)
        field = _SR_CATEGORICAL_FIELDS.get(indicator) or _SR_NUMERIC_FIELDS.get(indicator)
        return _present(row, f"{prefix}_{direction.lower()}_{field}") if prefix else None
    if indicator in _RESEARCH_NUMERIC_FIELDS:
        _feature, column, scale = _RESEARCH_NUMERIC_FIELDS[indicator]
        value = _number(_present(row, column))
        return value * float(scale) if math.isfinite(value) else None
    if indicator in _RESEARCH_CATEGORICAL_FIELDS:
        _feature, column = _RESEARCH_CATEGORICAL_FIELDS[indicator]
        return _present(row, column)
    # Any remaining strategy-specific evidence is not fully preserved in the
    # immutable feature-context contract. Missing evidence must never be guessed.
    return None


def _condition_match(
    row: dict[str, Any],
    direction: str,
    profile: str,
    condition: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    value = _evidence(row, direction, profile, condition, config)
    operator = str(condition.get("condition", "EQUALS")).upper()
    indicator = str(condition.get("indicator", "")).upper()
    detail = {
        "condition_id": condition.get("id"), "indicator": indicator,
        "condition": operator, "observed": _json_safe(value),
    }
    if value is None:
        detail.update(matched=False, availability="MISSING_OR_UNSUPPORTED")
        return False, detail
    if operator in {"EQUALS", "NOT_EQUALS"}:
        target = condition.get("value")
        observed_number, target_number = _number(value), _number(target)
        if not isinstance(target, str) and math.isfinite(observed_number) and math.isfinite(target_number):
            equals = observed_number == target_number
        else:
            observed_category = _category(value)
            target_category = _category(target)
            preset_members = CATEGORICAL_RULE_PRESETS.get(indicator, {}).get(
                target_category or ""
            )
            equals = (
                observed_category in preset_members
                if preset_members
                else observed_category == target_category
            )
        matched = equals if operator == "EQUALS" else not equals
    else:
        observed = _number(value)
        if not math.isfinite(observed):
            detail.update(matched=False, availability="NON_NUMERIC")
            return False, detail
        if operator in {"GT", "GTE", "LT", "LTE"}:
            threshold = _number(condition.get("value"))
            if not math.isfinite(threshold):
                raise ValueError(f"numeric condition for {indicator} has an invalid threshold")
            matched = {
                "GT": observed > threshold, "GTE": observed >= threshold,
                "LT": observed < threshold, "LTE": observed <= threshold,
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
    detail.update(matched=bool(matched), availability="AVAILABLE")
    return bool(matched), detail


def _group_match(
    row: dict[str, Any], direction: str, profile: str,
    group: dict[str, Any], config: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    if not bool(group.get("enabled", True)):
        return False, []
    conditions = group.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError(f"rule group {group.get('id')} has no conditions")
    details = []
    matched = True
    for condition in conditions:
        result, detail = _condition_match(row, direction, profile, condition, config)
        details.append(detail)
        matched = matched and result
    return matched, details


def _rule_decision(
    row: dict[str, Any], profile: str, source_side: str,
    groups: dict[str, list[dict[str, Any]]], config: dict[str, Any],
) -> dict[str, Any]:
    entry_groups = [group for group in groups.get("ENTRY", []) if bool(group.get("enabled", True))]
    entry_matches: list[str] = []
    diagnostics = []
    for group in entry_groups:
        matched, details = _group_match(row, source_side, profile, group, config)
        diagnostics.append({"group_id": group.get("id"), "matched": matched, "conditions": details})
        if matched:
            entry_matches.append(str(group.get("id")))
    # FLIP is a complete positive setup thesis, not merely an ENTRY modifier.
    # Evaluate it even when no ENTRY group matched so an already-learned FLIP can
    # independently admit the opposite executable side.
    flip_matches = []
    for group in groups.get("FLIP", []):
        matched, _ = _group_match(row, source_side, profile, group, config)
        if matched:
            flip_matches.append(str(group.get("id")))

    if not entry_matches and not flip_matches:
        return {
            "eligible": False,
            "reason": "NO_ENTRY_OR_FLIP_GROUP_MATCH",
            "entry_diagnostics": diagnostics,
        }

    # Preserve historical precedence for normal ENTRY admissions: a matching
    # source-side VETO still blocks the trade before an optional FLIP can invert
    # execution. A standalone FLIP has no source ENTRY to veto, so it admits the
    # opposite side directly.
    veto_matches = []
    if entry_matches:
        for group in groups.get("VETO", []):
            matched, _ = _group_match(row, source_side, profile, group, config)
            if matched:
                veto_matches.append(str(group.get("id")))
        if veto_matches:
            return {
                "eligible": False, "reason": "VETO_GROUP_MATCH",
                "matched_entry_groups": entry_matches,
                "matched_veto_groups": veto_matches,
                "matched_flip_groups": flip_matches,
            }

    effective_side = (
        "SHORT" if source_side == "LONG" else "LONG"
    ) if flip_matches else source_side
    return {
        "eligible": True,
        "reason": "ENTRY_MATCHED" if entry_matches else "FLIP_MATCHED_WITHOUT_ENTRY",
        "matched_entry_groups": entry_matches,
        "matched_veto_groups": [],
        "matched_flip_groups": flip_matches,
        "rule_effective_side": effective_side,
    }


def _ichimoku_trade_context(
    context: dict[str, Any],
    *,
    strategy_timeframe_minutes: int | None,
) -> dict[str, Any]:
    """Build a compact explicit Ichimoku block without requiring it to exist.

    Older immutable reference runs may predate Ichimoku research entirely. Those
    runs remain valid: the block reports unavailable rather than raising or
    inventing evidence.
    """
    timeframes: dict[str, dict[str, Any]] = {}
    targets = (
        ("STRATEGY_TF", "", strategy_timeframe_minutes),
        ("1H", "ich_1h_", 60),
        ("4H", "ich_4h_", 240),
        ("1D", "ich_1d_", 1440),
    )
    for label, prefix, default_minutes in targets:
        values: dict[str, Any] = {}
        if prefix:
            completed_name = f"{prefix}completed_candle_time"
            timeframe_name = f"{prefix}timeframe_minutes"
            field_name = lambda field: f"{prefix}{field}"
        else:
            completed_name = "ichimoku_completed_candle_time"
            timeframe_name = "ichimoku_timeframe_minutes"
            field_name = lambda field: field

        completed = _json_safe(context.get(completed_name))
        raw_minutes = _json_safe(context.get(timeframe_name))
        if completed is not None:
            values["completed_candle_time"] = completed
        if raw_minutes is not None:
            values["timeframe_minutes"] = raw_minutes
        elif default_minutes:
            values["timeframe_minutes"] = int(default_minutes)

        evidence_count = 0
        for field in _ICHIMOKU_SUMMARY_FIELDS:
            value = _json_safe(context.get(field_name(field)))
            if value is None:
                continue
            values[field] = value
            evidence_count += 1

        # Do not advertise a timeframe merely because a default timeframe number
        # exists; at least one actual Ichimoku evidence field must be present.
        if evidence_count:
            timeframes[label] = values

    available = bool(timeframes)
    return {
        "contract": _ICHIMOKU_CONTEXT_CONTRACT,
        "available": available,
        "availability_reason": (
            "AVAILABLE"
            if available
            else "NOT_PRESENT_IN_REFERENCE_RUN"
        ),
        "review_instruction": (
            "When available, explicitly assess Ichimoku alongside S/R, DI/ADX, "
            "EMA/MR, MACD/momentum and flow. Treat it as causal supporting "
            "evidence; do not force a rule from one observation. When unavailable, "
            "do not infer or reconstruct Ichimoku from later data."
        ),
        "timeframes": timeframes,
    }


def _safe_context(
    row: dict[str, Any],
    context: dict[str, Any],
    *,
    direction: str | None = None,
    profile: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trade = {}
    for name in _SAFE_TRADE_ENTRY_COLUMNS:
        if name in row:
            value = _json_safe(row[name])
            if value is not None:
                trade[name] = value
    feature = {}
    raw_sr_prefixes = ("sr_strategy_", "sr_1h_", "sr_4h_", "sr_1d_")
    for name, raw in context.items():
        if str(name).startswith(raw_sr_prefixes):
            continue
        value = _json_safe(raw)
        if value is not None:
            feature[str(name)] = value

    result = {
        "trade_entry_context": trade,
        # PreparedBacktestFrame validates that every value in this artifact is
        # available no later than the decision candle completes.
        "feature_context": feature,
        "ichimoku_trade_context_v1": _ichimoku_trade_context(
            context,
            strategy_timeframe_minutes=(
                int((config.get("data") or {}).get("strategy_timeframe_minutes", 0) or 0)
                if isinstance(config, dict)
                else None
            ),
        ),
    }
    if direction in {"LONG", "SHORT"} and profile and isinstance(config, dict):
        timeframe_context = {}
        for label, timeframe in (
            ("STRATEGY_TF", 0),
            ("1H", 60),
            ("4H", 240),
            ("1D", 1440),
        ):
            derived = _wf_trade_relative_sr(
                row,
                direction,
                profile,
                {"sr_timeframe_minutes": timeframe},
                config,
            )
            if derived is None:
                continue
            timeframe_context[label] = {
                key.removeprefix("SR_").lower(): _json_safe(value)
                for key, value in derived.items()
                if _json_safe(value) is not None
            }
        result["support_resistance_trade_context_v2"] = {
            "direction": direction,
            "strategy_timeframe_minutes": (config.get("data") or {}).get(
                "strategy_timeframe_minutes"
            ),
            "unit_definitions": {
                "selected_tf_atr": (
                    "ATR calculated on the selected S/R timeframe; values from "
                    "different S/R timeframes are not directly comparable."
                ),
                "strategy_tf_atr": "ATR calculated on the strategy/entry timeframe.",
                "room_r": (
                    "absolute distance to opposing zone edge divided by the "
                    "configured stop distance; 1.0 means one full trade R."
                ),
                "room_target_multiple": (
                    "absolute distance to opposing zone edge divided by the planned "
                    "final target distance; 1.0 means the target reaches the zone edge."
                ),
            },
            "timeframes": timeframe_context,
        }
    return result


def _next_teacher(
    manifest: dict[str, Any], run_dir: Path, events: list[dict[str, Any]]
) -> tuple[dict[str, Any], pd.Timestamp] | None:
    if "trades" not in (manifest.get("artifacts") or {}):
        return None
    path = artifact_path(run_dir, manifest, "trades", verify=True)
    last = _last_teacher_time(events)
    with duckdb.connect(":memory:") as connection:
        columns = set(_columns(connection, path))
        required = {"pair_id", "pair_net_r", "exit_time"}
        if required - columns:
            return None
        optional = [name for name in ("trade_id", "side", "strategy_profile_key", "entry_time") if name in columns]
        selection = ["pair_id", *optional, "exit_time"]
        where = "pair_net_r > 0"
        params: list[Any] = []
        if last is not None:
            where += " AND CAST(exit_time AS TIMESTAMPTZ) > ?"
            params.append(last.to_pydatetime())
        row = connection.execute(
            f"SELECT {', '.join(selection)} FROM read_parquet('{_quote(path)}') "
            f"WHERE {where} ORDER BY CAST(exit_time AS TIMESTAMPTZ), CAST(pair_id AS VARCHAR) LIMIT 1",
            params,
        ).fetchone()
    if row is None:
        return None
    values = dict(zip(selection, row))
    resolved = _utc_timestamp(values.pop("exit_time"), "teacher exit_time")
    boundary = {key: _json_safe(value) for key, value in values.items()}
    boundary["resolution_time"] = resolved.isoformat()
    return boundary, resolved


def _idempotent_candidate(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": CANDIDATE_CONTEXT_CONTRACT,
        "status": "CANDIDATE_CAPTURED",
        "experiment_id": event["experiment_id"],
        "sequence": event["sequence"],
        "state_hash": event["resulting_state_hash"],
        "previous_state_hash": event["previous_state_hash"],
        "candidate": deepcopy(event["payload"]),
        "idempotent_replay": True,
        "next_required_event": "DECISION_FROZEN",
        "decision_state_hash": event["resulting_state_hash"],
        "outcome_exposed": False,
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
    """Apply current causal rules to paired WF source rows and capture the first match."""
    if isinstance(max_scan_rows, bool) or not isinstance(max_scan_rows, int):
        raise ValueError("max_scan_rows must be an integer")
    if not 1 <= max_scan_rows <= MAX_SCAN_ROWS:
        raise ValueError(f"max_scan_rows must be between 1 and {MAX_SCAN_ROWS}")

    store = CausalExperimentStore(Path(control.project_root) / "walk_forward_experiments")
    current_events = _events(store, experiment_id)
    replay = _existing_operation(current_events, operation_id)
    if replay is not None:
        return _idempotent_candidate(replay)

    readback, events = _verified_head(
        store, experiment_id, expected_sequence, expected_state_hash
    )
    unresolved = _open_candidate(events)
    if unresolved is not None:
        candidate_id, state = unresolved
        raise ValueError(
            f"candidate {candidate_id} is still {state}; finish or invalidate it before scanning ahead"
        )

    snapshot = materialize_walk_forward_strategy(
        control, reports, experiment_id=experiment_id,
        expected_sequence=expected_sequence, expected_state_hash=expected_state_hash,
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
    if _sampling_mode(reference_manifest) != "WALK_FORWARD":
        raise ValueError(
            "reference run must use WALK_FORWARD paired LONG+SHORT research sampling "
            "for deterministic candidate selection"
        )
    samples_path = _artifact(reference_manifest, run_dir, "research_sampling_trades")
    context_path = _artifact(reference_manifest, run_dir, "feature_context")

    teacher = _next_teacher(reference_manifest, run_dir, events)
    cursor = _max_event_time(events)
    scan_columns = _rule_scan_columns(groups_by_profile, config)
    frame = _candidate_rows(
        samples_path,
        context_path,
        cursor,
        max_scan_rows,
        required_columns=scan_columns,
    )
    seen_samples, seen_identities = _seen_keys(events)
    counters = {
        "rows_scanned": 0, "skipped_seen": 0,
        "skipped_disabled_profiles": 0, "rejected_by_current_rules": 0,
    }

    for _, series in frame.iterrows():
        counters["rows_scanned"] += 1
        row, feature_context = _row_maps(series)
        signal_index = int(row["research_signal_index"])
        source_side = str(row["side"]).upper()
        profile = str(row.get("strategy_profile_key", "")).lower()
        sample_id = str(row.get("research_sample_id", "") or "").strip()
        if (sample_id and sample_id in seen_samples) or (signal_index, source_side) in seen_identities:
            counters["skipped_seen"] += 1
            continue
        profile_cfg = ((config.get("strategy") or {}).get("profiles") or {}).get(profile) or {}
        if profile not in PROFILE_KEYS or profile not in groups_by_profile or not bool(profile_cfg.get("enabled", False)):
            counters["skipped_disabled_profiles"] += 1
            continue
        decision = _rule_decision(
            row, profile, source_side, groups_by_profile[profile], config
        )
        if not decision.get("eligible"):
            counters["rejected_by_current_rules"] += 1
            continue

        entry_time = _utc_timestamp(row["entry_time"], "candidate entry_time")
        raw_decision_time = _present(feature_context, "decision_available_at")
        if raw_decision_time is None:
            raw_decision_time = row.get("signal_available_at", entry_time)
        decision_time = _utc_timestamp(raw_decision_time, "candidate decision_available_at")
        if teacher is not None and teacher[1] <= decision_time:
            return {
                "contract": CANDIDATE_CONTEXT_CONTRACT,
                "status": "TEACHER_DUE_FIRST",
                "experiment_id": experiment_id,
                "sequence": int(expected_sequence), "state_hash": str(expected_state_hash),
                "teacher_boundary": teacher[0], "candidate_not_captured": True,
                "scan": counters, "outcome_exposed": False,
            }

        detail_series = _candidate_detail_row(
            samples_path, context_path, signal_index, source_side
        )
        full_row, full_feature_context = _row_maps(detail_series)
        full_profile = str(full_row.get("strategy_profile_key", "")).lower()
        if full_profile != profile:
            raise ValueError(
                "projected walk-forward scan profile disagrees with hydrated candidate"
            )
        verified_decision = _rule_decision(
            full_row,
            full_profile,
            source_side,
            groups_by_profile[full_profile],
            config,
        )
        decision_keys = (
            "eligible",
            "reason",
            "matched_entry_groups",
            "matched_veto_groups",
            "matched_flip_groups",
            "rule_effective_side",
        )
        if any(
            verified_decision.get(key) != decision.get(key)
            for key in decision_keys
        ):
            raise ValueError(
                "projected walk-forward rule evaluation disagrees with full candidate context"
            )
        row = full_row
        feature_context = full_feature_context
        profile = full_profile
        decision = verified_decision
        sample_id = str(row.get("research_sample_id", "") or "").strip()

        candidate_id = f"{signal_index}-{source_side.lower()}"
        if CausalExperimentStore._candidate_state(events, candidate_id) != "UNSEEN":
            suffix = hashlib.sha256(f"{sample_id}:{profile}".encode()).hexdigest()[:8]
            candidate_id = f"{candidate_id}-{suffix}"
        safe = _safe_context(
            row,
            feature_context,
            direction=source_side,
            profile=profile,
            config=config,
        )
        core = {
            "contract": CANDIDATE_CONTEXT_CONTRACT,
            "experiment_id": experiment_id,
            "experiment_sequence_before_capture": int(expected_sequence),
            "experiment_state_hash_before_capture": str(expected_state_hash),
            "strategy_snapshot_sha256": snapshot["snapshot_sha256"],
            "reference_run": reference_run,
            "reference_sample_id": sample_id or None,
            "reference_walk_forward_candidate_id": (
                _json_safe(row.get("walk_forward_candidate_id")) or None
            ),
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
        feature_hash = canonical_sha256(core)
        token = canonical_sha256({
            "experiment_id": experiment_id, "sequence": int(expected_sequence),
            "state_hash": str(expected_state_hash), "snapshot": snapshot["snapshot_sha256"],
            "candidate_id": candidate_id, "reference_sample_id": sample_id or None,
            "research_signal_index": signal_index, "feature_hash": feature_hash,
        })
        payload = {**core, "feature_hash": feature_hash, "candidate_token": token}
        appended = store.append_event(
            experiment_id, "CANDIDATE_CONTEXT_CAPTURED", payload, operation_id,
            int(expected_sequence), str(expected_state_hash),
            effective_market_time=entry_time.isoformat(),
            source="DETERMINISTIC_CANDIDATE_ENGINE",
        )
        return {
            "contract": CANDIDATE_CONTEXT_CONTRACT,
            "status": "CANDIDATE_CAPTURED",
            "experiment_id": experiment_id,
            "sequence": appended["sequence"], "state_hash": appended["state_hash"],
            "previous_state_hash": str(expected_state_hash), "candidate": payload,
            "idempotent_replay": False, "scan": counters,
            "next_required_event": "DECISION_FROZEN",
            "decision_state_hash": appended["state_hash"], "outcome_exposed": False,
        }

    if teacher is not None:
        return {
            "contract": CANDIDATE_CONTEXT_CONTRACT,
            "status": "TEACHER_DUE_FIRST",
            "experiment_id": experiment_id,
            "sequence": int(expected_sequence), "state_hash": str(expected_state_hash),
            "teacher_boundary": teacher[0], "candidate_not_captured": True,
            "scan": counters, "outcome_exposed": False,
        }
    return {
        "contract": CANDIDATE_CONTEXT_CONTRACT,
        "status": "NO_ELIGIBLE_CANDIDATE_IN_SCAN",
        "experiment_id": experiment_id,
        "sequence": int(expected_sequence), "state_hash": str(expected_state_hash),
        "scan": {**counters, "max_scan_rows": max_scan_rows},
        "outcome_exposed": False,
    }
