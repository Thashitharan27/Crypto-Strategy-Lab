"""Read-only completed-run visualization model for Strategy Visualizer.

This module never re-runs strategy logic. It reads the immutable completed-run
artifacts plus the canonical market-data slice used by the workstation and
builds a bounded JSON payload for the desktop chart.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import json
import math
from typing import Any, Mapping

import duckdb
import numpy as np
import pandas as pd

from crypto_strategy_lab.data import DatasetKind
from crypto_strategy_lab.data.timing import interval_to_timedelta
from crypto_strategy_lab.data.source_identity import SourceSignature
from crypto_strategy_lab.gui.completed_run_research import research_seed_from_manifest
from crypto_strategy_lab.research_warmup import expand_strategy_request
from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_VALUE_CODES,
    is_context_timeframe_evidence,
)


LIGHTWEIGHT_CHARTS_VERSION = "5.2.1"
LIGHTWEIGHT_CHARTS_URL = (
    "https://cdn.jsdelivr.net/npm/lightweight-charts@"
    f"{LIGHTWEIGHT_CHARTS_VERSION}/dist/lightweight-charts.standalone.production.js"
)

DEFAULT_VISIBLE_CANDLES = 240
EMA_WARMUP_BARS = 220
MIN_VISIBLE_CANDLES = 60
MAX_VISIBLE_CANDLES = 5000

SR_TIMEFRAMES = {
    "strategy": "Strategy TF",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}

_CONTEXT_INSPECTOR_FIELDS = (
    ("adx", "ADX"),
    ("plus_di", "+DI"),
    ("minus_di", "-DI"),
    ("di_spread", "DI Spread"),
    ("di_ratio", "DI Ratio"),
    ("session_vwap", "VWAP"),
    ("market_regime", "Regime"),
    ("mean_reversion_state", "MR State"),
    ("mean_reversion_motion", "MR Motion"),
    ("sr_strategy_long_support_state", "Strategy Support"),
    ("sr_strategy_long_resistance_state", "Strategy Resistance"),
    ("sr_1h_long_support_state", "1H Support"),
    ("sr_1h_long_resistance_state", "1H Resistance"),
    ("sr_4h_long_support_state", "4H Support"),
    ("sr_4h_long_resistance_state", "4H Resistance"),
    ("sr_1d_long_support_state", "1D Support"),
    ("sr_1d_long_resistance_state", "1D Resistance"),
)


def _utc(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("timestamp is missing")
    return (
        timestamp.tz_localize("UTC")
        if timestamp.tzinfo is None
        else timestamp.tz_convert("UTC")
    )


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return _finite(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return str(getattr(value, "value", value))


def _unix_seconds(value: Any) -> int:
    return int(_utc(value).timestamp())


def _first_value(row: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if value is None or value is pd.NA:
            continue
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def _ema(values: pd.Series, period: int) -> np.ndarray:
    """Display-only EMA using the same causal formula as the native engine."""
    numeric = pd.to_numeric(values, errors="coerce")
    return (
        numeric.ewm(span=period, adjust=False, min_periods=period)
        .mean()
        .to_numpy(float)
    )


def _line_points(times: pd.Series, values: Any) -> list[dict[str, Any]]:
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(float)
    result: list[dict[str, Any]] = []
    for timestamp, value in zip(times, numeric):
        if math.isfinite(float(value)):
            result.append({"time": _unix_seconds(timestamp), "value": float(value)})
    return result


def _categorical_context(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column, label in _CONTEXT_INSPECTOR_FIELDS:
        if column not in row:
            continue
        value = _json_value(row[column])
        if value is not None:
            result[label] = value
    return result


def _trade_result_label(row: Mapping[str, Any]) -> str:
    net_r = _finite(row.get("pair_net_r"))
    if net_r is None:
        return ""
    return f"{net_r:+.3f}R"


def _trade_side(row: Mapping[str, Any]) -> str:
    side = str(row.get("side") or row.get("trade_direction") or "").upper()
    return side if side in {"LONG", "SHORT"} else side or "UNKNOWN"


def _rule_actual_display(evidence: str, value: Any, available: bool) -> str:
    if not available:
        return "MISSING"
    numeric = _finite(value)
    codes = CATEGORICAL_VALUE_CODES.get(str(evidence).upper())
    if codes and numeric is not None:
        for label, code in codes.items():
            if abs(float(code) - numeric) < 1e-9:
                return str(label)
    if numeric is not None:
        return f"{numeric:.6g}"
    return str(value)


def _rule_requirement(operator: Any, first: Any, second: Any) -> str:
    op = str(operator or "").upper()
    left = "" if first is None or pd.isna(first) else str(first)
    right = "" if second is None or pd.isna(second) else str(second)
    if op == "GT":
        return f"> {left}"
    if op == "GTE":
        return f">= {left}"
    if op == "LT":
        return f"< {left}"
    if op == "LTE":
        return f"<= {left}"
    if op == "BETWEEN":
        return f"{left} to {right}"
    if op == "OUTSIDE":
        return f"outside {left} to {right}"
    if op == "IS":
        return f"is {left}"
    if op == "IS_NOT":
        return f"is not {left}"
    return " ".join(part for part in (op, left, right) if part)


def _rule_timeframe_label(evidence: str, value: Any) -> str:
    if value is None or pd.isna(value):
        return "Configured S/R TF" if is_context_timeframe_evidence(evidence) else "Strategy TF"
    minutes = int(float(value))
    return {0: "Strategy TF", 60: "1H", 240: "4H", 1440: "1D"}.get(
        minutes, f"{minutes}m"
    )



def trade_stop_target(row: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """Return the best immutable entry-stop / target representation available."""
    side = _trade_side(row).lower()
    stop = _first_value(
        row,
        (
            "initial_stop_price",
            f"{side}_original_sl",
            f"{side}_sl_price",
            f"{side}_original_stop",
            f"{side}_sl",
        ),
    )
    target = _first_value(
        row,
        (
            "initial_target_price",
            f"{side}_tp",
            f"{side}_tp2_price",
            f"{side}_tp1_price",
        ),
    )
    return _finite(stop), _finite(target)


@dataclass
class CompletedRunVisualizer:
    service: Any
    run_dir: Path
    manifest: dict[str, Any]
    trades_path: Path
    signals_path: Path | None
    context_path: Path | None
    sr_zones_path: Path | None
    rule_trace_path: Path | None
    source_archives_path: Path | None
    source_verified: bool | None
    seed: Any
    trades: pd.DataFrame

    @classmethod
    def load(
        cls,
        service: Any,
        run_dir: Path,
        manifest: Mapping[str, Any] | None = None,
    ) -> "CompletedRunVisualizer":
        run_dir = Path(run_dir)
        if manifest is None:
            manifest, _summary = service.completed_runs.read(run_dir)
        manifest = dict(manifest)
        seed = research_seed_from_manifest(manifest)

        completed = service.completed_runs
        trades_path = completed.artifact_path(run_dir, manifest, "trades")
        signals_path = cls._optional_artifact(completed, run_dir, manifest, "signals")
        context_path = cls._optional_artifact(
            completed, run_dir, manifest, "feature_context"
        )
        sr_zones_path = cls._optional_artifact(
            completed, run_dir, manifest, "sr_zones"
        )
        rule_trace_path = cls._optional_artifact(
            completed, run_dir, manifest, "rule_trace"
        )
        source_archives_path = cls._optional_artifact(
            completed, run_dir, manifest, "source_archives"
        )
        source_verified = cls._verify_market_source(
            service, seed, source_archives_path
        )
        trades = cls._read_parquet(trades_path)
        if not trades.empty:
            timestamp_column = cls._trade_timestamp_column(trades)
            trades[timestamp_column] = pd.to_datetime(
                trades[timestamp_column], utc=True, errors="coerce"
            )
            trades = trades.sort_values(timestamp_column, kind="stable").reset_index(
                drop=True
            )
        return cls(
            service=service,
            run_dir=run_dir,
            manifest=manifest,
            trades_path=trades_path,
            signals_path=signals_path,
            context_path=context_path,
            sr_zones_path=sr_zones_path,
            rule_trace_path=rule_trace_path,
            source_archives_path=source_archives_path,
            source_verified=source_verified,
            seed=seed,
            trades=trades,
        )

    @staticmethod
    def _optional_artifact(completed, run_dir, manifest, name):
        if name not in (manifest.get("artifacts") or {}):
            return None
        return completed.artifact_path(run_dir, manifest, name)

    @staticmethod
    def _verify_market_source(service, seed, source_path: Path | None) -> bool | None:
        """Verify chart OHLC resolves to the same canonical partitions as the run."""
        if source_path is None:
            return None
        escaped = str(source_path).replace("'", "''")
        interval = str(seed.request.strategy_timeframe)
        with duckdb.connect(":memory:") as connection:
            rows = connection.execute(
                f"SELECT canonical_partition_identity FROM read_parquet('{escaped}') "
                "WHERE lower(CAST(dataset AS VARCHAR)) = 'klines' "
                "AND CAST(interval AS VARCHAR) = ?",
                [interval],
            ).fetchall()
        identities = [str(row[0]) for row in rows if row and row[0]]
        if not identities:
            raise ValueError(
                "completed run provenance does not contain its strategy-candle source identities"
            )
        expected = SourceSignature.from_canonical_identities(
            DatasetKind.KLINES, identities
        ).cache_identity()
        request = seed.request.to_data_request((DatasetKind.KLINES,))

        # Completed-run provenance records every source partition selected by the
        # real research load. ResearchRunner expands the strategy-history start
        # for causal indicator/S/R warm-up before that selection, so verification
        # must reconstruct the same expanded request rather than compare only the
        # user-visible research range.
        earliest_start = None
        catalog = getattr(service.store, "catalog", None)
        if catalog is not None and hasattr(catalog, "coverage"):
            try:
                coverage = catalog.coverage(
                    service.store.raw_root,
                    market=request.market,
                    dataset=DatasetKind.KLINES,
                    symbol=request.symbol,
                    interval=request.strategy_interval,
                )
                earliest_start = coverage.first_period
            except Exception:
                earliest_start = None
        source_request = expand_strategy_request(
            request,
            seed.config,
            earliest_start=earliest_start,
        )
        current = service.store.canonical_source_identity(
            source_request, DatasetKind.KLINES, interval=interval
        ).cache_identity()
        if current != expected:
            raise ValueError(
                "current canonical candle source does not match the completed run provenance; "
                "the underlying archive set was changed or repaired after this run"
            )
        return True

    @staticmethod
    def _read_parquet(path: Path) -> pd.DataFrame:
        escaped = str(path).replace("'", "''")
        with duckdb.connect(":memory:") as connection:
            return connection.execute(
                f"SELECT * FROM read_parquet('{escaped}')"
            ).df()

    @staticmethod
    def _trade_timestamp_column(frame: pd.DataFrame) -> str:
        for name in ("entry_time", "strategy_entry_time", "actual_entry_timestamp"):
            if name in frame.columns:
                return name
        raise ValueError("completed trades do not contain an entry timestamp")

    def available_chart_timeframes(self) -> list[dict[str, Any]]:
        """Return cached/canonical kline intervals available for visual reference.

        The strategy timeframe is always present. Other intervals come from the
        current Data Lake catalog and are reference-only; they never change the
        completed-run strategy or its persisted evidence.
        """
        request = self.seed.request
        strategy = str(request.strategy_timeframe)
        run_start = _utc(request.period_start)
        run_end = _utc(request.period_end)
        available: dict[str, dict[str, Any]] = {
            strategy: {
                "interval": strategy,
                "coverage": "full",
                "strategyTimeframe": True,
                "first": run_start.isoformat(),
                "last": run_end.isoformat(),
            }
        }
        store = getattr(self.service, "store", None)
        catalog = getattr(store, "catalog", None)
        raw_root = getattr(store, "raw_root", None)
        if catalog is None or raw_root is None or not hasattr(catalog, "inventory"):
            return list(available.values())
        try:
            rows = catalog.inventory(raw_root, market=request.market)
        except Exception:
            return list(available.values())

        for row in rows:
            if str(row.get("exchange") or "").lower() != str(request.exchange).lower():
                continue
            if str(row.get("symbol") or "").upper() != str(request.symbol).upper():
                continue
            if str(row.get("dataset") or "").lower() != DatasetKind.KLINES.value:
                continue
            interval = str(row.get("interval") or "").strip()
            if not interval:
                continue
            first_raw = row.get("first_period")
            last_raw = row.get("last_period")
            if first_raw is None or last_raw is None:
                continue
            first = _utc(first_raw)
            last = _utc(last_raw)
            if last <= run_start or first >= run_end:
                continue
            coverage = (
                "full"
                if first <= run_start and last >= run_end
                else "partial"
            )
            available[interval] = {
                "interval": interval,
                "coverage": coverage,
                "strategyTimeframe": interval == strategy,
                "first": first.isoformat(),
                "last": last.isoformat(),
            }

        def order(item: dict[str, Any]):
            try:
                return pd.Timedelta(interval_to_timedelta(item["interval"]))
            except Exception:
                return pd.Timedelta.max

        return sorted(available.values(), key=order)

    def selected_trade_candle_time(self, index: int | None) -> pd.Timestamp | None:
        if index is None or not self.trade_count:
            return None
        row = self._trade_row(index)
        value = _first_value(
            row,
            (
                "research_signal_candle_open_time",
                "signal_candle_time",
                "strategy_candle_open_time",
            ),
        )
        return _utc(value) if value is not None else None

    def rule_inspector_at(self, timestamp: Any) -> dict[str, Any]:
        """Return exact decision-time authored rule observations for one candle."""
        target = _utc(timestamp)
        if self.rule_trace_path is None:
            return {
                "status": "LEGACY_UNAVAILABLE",
                "timestamp": target.isoformat(),
                "message": (
                    "This completed run predates rule_trace.parquet. Re-run the same "
                    "configuration to capture exact ENTRY/VETO/FLIP condition traces."
                ),
                "rows": [],
            }
        escaped = str(self.rule_trace_path).replace("'", "''")
        with duckdb.connect(":memory:") as connection:
            connection.execute("SET TimeZone='UTC'")
            frame = connection.execute(
                f"SELECT * FROM read_parquet('{escaped}') "
                "WHERE CAST(strategy_candle_open_time AS TIMESTAMPTZ)=? "
                "ORDER BY rule_kind, group_id, condition_order",
                [target.to_pydatetime()],
            ).df()
        if frame.empty:
            return {
                "status": "NOT_EVALUATED",
                "timestamp": target.isoformat(),
                "message": (
                    "No authored rule evaluation was recorded on this candle. The "
                    "strategy may have been in an active trade, outside its entry "
                    "cadence, or without a valid signal/profile context."
                ),
                "rows": [],
            }

        first = frame.iloc[0]
        rows = []
        for _, raw in frame.iterrows():
            evidence = str(raw.get("evidence") or "")
            kind = str(raw.get("rule_kind") or "").upper()
            enabled = bool(raw.get("group_enabled"))
            group_evaluated = bool(raw.get("group_evaluated"))
            matched = bool(raw.get("group_matched"))
            if not enabled:
                group_status = "MUTED"
            elif not group_evaluated:
                group_status = "NOT REACHED"
            elif kind == "REQUIRED":
                group_status = "MATCHED" if matched else "FAILED"
            else:
                group_status = "TRIGGERED" if matched else "CLEAR"
            condition_evaluated = bool(raw.get("condition_evaluated"))
            available = bool(raw.get("evidence_available"))
            condition_passed = bool(raw.get("condition_passed"))
            rows.append(
                {
                    "type": "ENTRY" if kind == "REQUIRED" else kind,
                    "group": str(raw.get("group_name") or raw.get("group_id") or ""),
                    "groupStatus": group_status,
                    "evidence": evidence,
                    "timeframe": _rule_timeframe_label(
                        evidence, raw.get("timeframe_minutes")
                    ),
                    "actual": (
                        _rule_actual_display(evidence, raw.get("actual_value"), available)
                        if condition_evaluated else "—"
                    ),
                    "requirement": _rule_requirement(
                        raw.get("operator"),
                        raw.get("expected_value"),
                        raw.get("expected_value2"),
                    ),
                    "conditionStatus": (
                        "NOT REACHED"
                        if not condition_evaluated
                        else "MISSING"
                        if not available
                        else "PASS"
                        if condition_passed
                        else "FAIL"
                    ),
                    "conditionPassed": condition_passed,
                    "groupMatched": matched,
                    "groupEnabled": enabled,
                }
            )
        return {
            "status": "AVAILABLE",
            "timestamp": target.isoformat(),
            "profile": _json_value(first.get("strategy_profile_key")),
            "side": _json_value(first.get("source_side")),
            "regime": _json_value(first.get("market_regime")),
            "signalStrategy": _json_value(first.get("signal_strategy")),
            "filterPassed": bool(first.get("filter_passed")),
            "filterReason": _json_value(first.get("filter_reason")),
            "message": "",
            "rows": rows,
        }

    @staticmethod
    def _sr_value(row: Mapping[str, Any], label: str, suffix: str) -> Any:
        candidates = [f"sr_{label}_{suffix}"]
        if label == "strategy":
            candidates.append(suffix)
            if suffix == "completed_candle_time":
                candidates.append("sr_completed_candle_time")
        return _first_value(row, tuple(candidates))

    @classmethod
    def _sr_inspector_block(
        cls, row: Mapping[str, Any], label: str
    ) -> dict[str, Any] | None:
        def long(field: str):
            return cls._sr_value(row, label, f"long_{field}")

        def short(field: str):
            return cls._sr_value(row, label, f"short_{field}")

        support_low = _finite(long("support_zone_low"))
        support_high = _finite(long("support_zone_high"))
        resistance_low = _finite(long("resistance_zone_low"))
        resistance_high = _finite(long("resistance_zone_high"))
        support_state = _json_value(long("support_state"))
        resistance_state = _json_value(long("resistance_state"))
        if (
            support_low is None
            and support_high is None
            and resistance_low is None
            and resistance_high is None
            and support_state is None
            and resistance_state is None
        ):
            return None

        strategy_atr = _finite(row.get("atr"))

        def strategy_atr_distance(price_distance: Any) -> float | None:
            distance = _finite(price_distance)
            if distance is None or strategy_atr is None or strategy_atr <= 0:
                return None
            return distance / strategy_atr

        conflict_raw = long("structure_conflict")
        if conflict_raw is None:
            conflict = bool(long("near_support")) and bool(long("near_resistance"))
        else:
            conflict = bool(conflict_raw)

        completed = cls._sr_value(row, label, "completed_candle_time")
        return {
            "key": label,
            "timeframe": SR_TIMEFRAMES[label],
            "supportZoneLow": support_low,
            "supportZoneHigh": support_high,
            "supportState": support_state,
            "supportDistanceNativeAtr": _finite(long("nearest_support_distance_atr")),
            "supportDistanceStrategyAtr": strategy_atr_distance(
                long("nearest_support_distance_price")
            ),
            "supportNear": bool(long("near_support")),
            "supportInside": bool(long("inside_support_zone")),
            "supportTested": bool(long("support_tested")),
            "supportHeld": bool(long("support_held")),
            "supportTests": _json_value(long("support_test_count")),
            "supportRejectionAtr": _finite(long("support_rejection_atr")),
            "supportBarsSinceTest": _json_value(long("bars_since_support_test")),
            "supportPivotIndex": _json_value(long("nearest_support_bar_index")),
            "supportLastBreakIndex": _json_value(long("support_last_break_index")),
            "supportBrokenZoneLow": _finite(long("support_broken_zone_low")),
            "supportBrokenZoneHigh": _finite(long("support_broken_zone_high")),
            "resistanceZoneLow": resistance_low,
            "resistanceZoneHigh": resistance_high,
            "resistanceState": resistance_state,
            "resistanceDistanceNativeAtr": _finite(
                long("nearest_resistance_distance_atr")
            ),
            "resistanceDistanceStrategyAtr": strategy_atr_distance(
                long("nearest_resistance_distance_price")
            ),
            "resistanceNear": bool(long("near_resistance")),
            "resistanceInside": bool(long("inside_resistance_zone")),
            "resistanceTested": bool(long("resistance_tested")),
            "resistanceHeld": bool(long("resistance_held")),
            "resistanceTests": _json_value(long("resistance_test_count")),
            "resistanceRejectionAtr": _finite(long("resistance_rejection_atr")),
            "resistanceBarsSinceTest": _json_value(
                long("bars_since_resistance_test")
            ),
            "resistancePivotIndex": _json_value(
                long("nearest_resistance_bar_index")
            ),
            "resistanceLastBreakIndex": _json_value(
                long("resistance_last_break_index")
            ),
            "resistanceBrokenZoneLow": _finite(
                long("resistance_broken_zone_low")
            ),
            "resistanceBrokenZoneHigh": _finite(
                long("resistance_broken_zone_high")
            ),
            "roomLongNativeAtr": _finite(long("room_in_direction_atr")),
            "roomShortNativeAtr": _finite(short("room_in_direction_atr")),
            "structureConflict": conflict,
            "confirmationRating": _json_value(long("confirmation_rating")),
            "completedCandleTime": (
                _utc(completed).isoformat() if completed is not None else None
            ),
        }

    @staticmethod
    def _expand_sr_snapshot_frame(frame: pd.DataFrame) -> pd.DataFrame:
        """Expand compact S/R snapshots only for the requested visualizer window."""
        if frame.empty or "zone_inventory_json" not in frame.columns:
            return frame
        records: list[dict[str, Any]] = []
        for _, snapshot in frame.iterrows():
            payload = snapshot.get("zone_inventory_json")
            if payload is None or pd.isna(payload):
                continue
            try:
                zones = json.loads(str(payload))
            except json.JSONDecodeError as exc:
                raise ValueError("completed run contains invalid S/R inventory JSON") from exc
            if not isinstance(zones, list):
                raise ValueError("completed run S/R inventory JSON is not a list")
            expected = snapshot.get("zone_count")
            if expected is not None and not pd.isna(expected) and len(zones) != int(expected):
                raise ValueError("completed run S/R snapshot zone_count mismatch")
            for zone in zones:
                if not isinstance(zone, dict):
                    raise ValueError("completed run S/R inventory entry is not an object")
                sources = zone.get("source_bar_indices") or []
                records.append({
                    "strategy_index": int(snapshot["strategy_index"]),
                    "strategy_candle_open_time": snapshot["strategy_candle_open_time"],
                    "decision_available_at": snapshot["decision_available_at"],
                    "sr_timeframe": snapshot["sr_timeframe"],
                    "sr_timeframe_minutes": int(snapshot["sr_timeframe_minutes"]),
                    "sr_completed_candle_time": snapshot.get("sr_completed_candle_time"),
                    "zone_id": str(zone.get("zone_id") or ""),
                    "structure": str(zone.get("structure") or ""),
                    "zone_low": zone.get("zone_low"),
                    "zone_high": zone.get("zone_high"),
                    "anchor_price": zone.get("anchor_price"),
                    "pivot_bar_index": zone.get("pivot_bar_index"),
                    "confirmed_at_index": zone.get("confirmed_at_index"),
                    "source_bar_indices_json": json.dumps(sources, separators=(",", ":")),
                    "source_count": zone.get("source_count", len(sources)),
                    "touch_count": zone.get("touch_count", 0),
                    "validation_rejection_atr": zone.get("validation_rejection_atr"),
                    "state": str(zone.get("state") or ""),
                    "tested": bool(zone.get("tested")),
                    "held": bool(zone.get("held")),
                    "rejection_atr": zone.get("rejection_atr"),
                    "test_count": zone.get("test_count", 0),
                    "bars_since_test": zone.get("bars_since_test"),
                    "last_test_index": zone.get("last_test_index"),
                    "distance_price": zone.get("distance_price"),
                    "distance_atr": zone.get("distance_atr"),
                    "near": bool(zone.get("near")),
                    "inside": bool(zone.get("inside")),
                    "nearest": bool(zone.get("nearest")),
                })
        result = pd.DataFrame.from_records(records)
        if not result.empty:
            result = result.sort_values(
                ["sr_timeframe_minutes", "structure", "zone_low", "zone_id", "strategy_index"],
                kind="stable",
            ).reset_index(drop=True)
        return result

    def _sr_zone_rows_at(self, timestamp: Any) -> list[dict[str, Any]]:
        if self.sr_zones_path is None:
            return []
        target = _utc(timestamp)
        escaped = str(self.sr_zones_path).replace("'", "''")
        with duckdb.connect(":memory:") as connection:
            connection.execute("SET TimeZone='UTC'")
            columns = {
                row[0]
                for row in connection.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{escaped}')"
                ).fetchall()
            }
            order_by = (
                "sr_timeframe_minutes"
                if "zone_inventory_json" in columns
                else "sr_timeframe_minutes, structure, zone_low, zone_id"
            )
            frame = connection.execute(
                f"SELECT * FROM read_parquet('{escaped}') "
                "WHERE CAST(strategy_candle_open_time AS TIMESTAMPTZ)=? "
                f"ORDER BY {order_by}",
                [target.to_pydatetime()],
            ).df()
        if frame.empty:
            return []
        frame = self._expand_sr_snapshot_frame(frame)
        if frame.empty:
            return []

        result: list[dict[str, Any]] = []
        for _, raw in frame.iterrows():
            label = str(raw.get("sr_timeframe") or "")
            result.append(
                {
                    "key": label,
                    "timeframe": SR_TIMEFRAMES.get(label, label),
                    "zoneId": str(raw.get("zone_id") or ""),
                    "structure": str(raw.get("structure") or "").upper(),
                    "zoneLow": _finite(raw.get("zone_low")),
                    "zoneHigh": _finite(raw.get("zone_high")),
                    "state": _json_value(raw.get("state")),
                    "nearest": bool(raw.get("nearest")),
                    "near": bool(raw.get("near")),
                    "inside": bool(raw.get("inside")),
                    "tested": bool(raw.get("tested")),
                    "held": bool(raw.get("held")),
                    "testCount": _json_value(raw.get("test_count")),
                    "touchCount": _json_value(raw.get("touch_count")),
                    "sourceCount": _json_value(raw.get("source_count")),
                    "validationRejectionAtr": _finite(
                        raw.get("validation_rejection_atr")
                    ),
                    "rejectionAtr": _finite(raw.get("rejection_atr")),
                    "distanceNativeAtr": _finite(raw.get("distance_atr")),
                    "distancePrice": _finite(raw.get("distance_price")),
                    "pivotIndex": _json_value(raw.get("pivot_bar_index")),
                    "confirmedAtIndex": _json_value(raw.get("confirmed_at_index")),
                    "barsSinceTest": _json_value(raw.get("bars_since_test")),
                    "lastTestIndex": _json_value(raw.get("last_test_index")),
                    "sourceBarIndices": _json_value(
                        raw.get("source_bar_indices_json")
                    ),
                    "completedCandleTime": (
                        _utc(raw.get("sr_completed_candle_time")).isoformat()
                        if raw.get("sr_completed_candle_time") is not None
                        and not pd.isna(raw.get("sr_completed_candle_time"))
                        else None
                    ),
                }
            )
        return result


    def sr_inspector_at(self, timestamp: Any) -> dict[str, Any]:
        """Return persisted S/R evidence for one exact strategy candle."""
        target = _utc(timestamp)
        if self.context_path is None:
            return {
                "status": "LEGACY_UNAVAILABLE",
                "timestamp": target.isoformat(),
                "message": "This completed run does not contain feature_context.parquet.",
                "timeframes": [],
            }
        escaped = str(self.context_path).replace("'", "''")
        with duckdb.connect(":memory:") as connection:
            frame = connection.execute(
                f"SELECT * FROM read_parquet('{escaped}') "
                "WHERE CAST(strategy_candle_open_time AS TIMESTAMPTZ)=? LIMIT 1",
                [target.to_pydatetime()],
            ).df()
        if frame.empty:
            return {
                "status": "NOT_AVAILABLE",
                "timestamp": target.isoformat(),
                "message": "No persisted S/R feature context exists on this candle.",
                "timeframes": [],
            }

        row = frame.iloc[0].to_dict()
        blocks = [
            block
            for label in SR_TIMEFRAMES
            if (block := self._sr_inspector_block(row, label)) is not None
        ]
        zones = self._sr_zone_rows_at(target)
        return {
            "status": "AVAILABLE" if blocks else "NOT_AVAILABLE",
            "timestamp": target.isoformat(),
            "message": "" if blocks else "No persisted S/R context exists on this candle.",
            "timeframes": blocks,
            "zones": zones,
            "zoneInventoryAvailable": self.sr_zones_path is not None,
        }

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    def trade_label(self, index: int) -> str:
        row = self._trade_row(index)
        pair_id = _json_value(row.get("pair_id")) or index + 1
        entry = _utc(
            _first_value(
                row,
                ("entry_time", "strategy_entry_time", "actual_entry_timestamp"),
            )
        )
        return (
            f"{index + 1}/{self.trade_count} · #{pair_id} · {_trade_side(row)} · "
            f"{_trade_result_label(row)} · {entry:%Y-%m-%d %H:%M}"
        )

    def _trade_row(self, index: int) -> dict[str, Any]:
        if not 0 <= int(index) < self.trade_count:
            raise IndexError("trade index is out of range")
        return self.trades.iloc[int(index)].to_dict()

    def selected_trade_summary(self, index: int | None) -> dict[str, Any]:
        if index is None or self.trade_count == 0:
            return {}
        row = self._trade_row(index)
        side = _trade_side(row)
        stop, target = trade_stop_target(row)
        entry = _finite(
            _first_value(row, ("entry_price", "actual_entry_price", "strategy_entry_price"))
        )
        exit_price = _finite(
            _first_value(row, (f"{side.lower()}_exit_price", "exit_price"))
        )
        exit_reason = _first_value(
            row,
            (f"{side.lower()}_final_exit_reason", f"{side.lower()}_exit_reason", "exit_reason"),
        )
        summary = {
            "Pair": _json_value(row.get("pair_id")),
            "Side": side,
            "Profile": _json_value(row.get("strategy_profile_key")),
            "Signal Strategy": _json_value(row.get("signal_strategy")),
            "Entry Time": _json_value(
                _first_value(row, ("entry_time", "strategy_entry_time"))
            ),
            "Entry": entry,
            "Stop": stop,
            "Target": target,
            "Exit Time": _json_value(row.get("exit_time")),
            "Exit": exit_price,
            "Exit Reason": _json_value(exit_reason),
            "Net R": _finite(row.get("pair_net_r")),
            "Net P&L": _finite(row.get("pair_net_pnl")),
            "Entry Filter": _json_value(row.get("entry_filter_reason")),
            "Regime": _json_value(row.get("market_regime")),
            "ADX": _finite(row.get("adx")),
            "+DI": _finite(row.get("plus_di")),
            "-DI": _finite(row.get("minus_di")),
            "DI Ratio": _finite(row.get("di_ratio")),
        }
        return {key: value for key, value in summary.items() if value is not None}

    def _center_time(self, trade_index: int | None) -> pd.Timestamp:
        if trade_index is not None and self.trade_count:
            row = self._trade_row(trade_index)
            return _utc(
                _first_value(
                    row,
                    ("entry_time", "strategy_entry_time", "actual_entry_timestamp"),
                )
            )
        interval = pd.Timedelta(
            interval_to_timedelta(self.seed.request.strategy_timeframe)
        )
        return _utc(self.seed.request.period_end) - interval

    def _window_bounds(
        self,
        trade_index: int | None,
        visible_candles: int,
        *,
        full_run: bool = False,
        chart_timeframe: str | None = None,
    ) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
        interval = pd.Timedelta(
            interval_to_timedelta(
                chart_timeframe or self.seed.request.strategy_timeframe
            )
        )
        run_start = _utc(self.seed.request.period_start)
        run_end = _utc(self.seed.request.period_end)
        if full_run:
            return run_start, run_start, run_end

        visible = max(
            MIN_VISIBLE_CANDLES,
            min(MAX_VISIBLE_CANDLES, int(visible_candles)),
        )
        center = self._center_time(trade_index)
        before = visible // 2
        after = visible - before
        visible_start = max(run_start, center - before * interval)
        visible_end = min(run_end, center + after * interval)
        calculation_start = max(
            run_start, visible_start - EMA_WARMUP_BARS * interval
        )
        return calculation_start, visible_start, visible_end

    def _market_frame(
        self,
        calculation_start: pd.Timestamp,
        visible_end: pd.Timestamp,
        *,
        chart_timeframe: str | None = None,
    ) -> pd.DataFrame:
        base_request = self.seed.request.to_data_request((DatasetKind.KLINES,))
        request = replace(
            base_request,
            start=calculation_start.to_pydatetime(),
            end=visible_end.to_pydatetime(),
            datasets=(DatasetKind.KLINES,),
        )
        frame = self.service.store.load_dataset(
            request,
            DatasetKind.KLINES,
            interval=chart_timeframe or self.seed.request.strategy_timeframe,
        )
        if frame.empty:
            return frame
        frame = frame.copy()
        frame["period_start"] = pd.to_datetime(
            frame["period_start"], utc=True, errors="raise"
        )
        return frame.sort_values("period_start", kind="stable").reset_index(drop=True)

    @staticmethod
    def _query_time_window(
        path: Path | None,
        timestamp_column: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        if path is None:
            return pd.DataFrame()
        escaped = str(path).replace("'", "''")
        escaped_column = '"' + timestamp_column.replace('"', '""') + '"'
        with duckdb.connect(":memory:") as connection:
            connection.execute("SET TimeZone='UTC'")
            columns = {
                row[0]
                for row in connection.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{escaped}')"
                ).fetchall()
            }
            if timestamp_column not in columns:
                return pd.DataFrame()
            query = (
                f"SELECT * FROM read_parquet('{escaped}') "
                f"WHERE CAST({escaped_column} AS TIMESTAMPTZ) >= ? "
                f"AND CAST({escaped_column} AS TIMESTAMPTZ) < ? "
                f"ORDER BY CAST({escaped_column} AS TIMESTAMPTZ)"
            )
            return connection.execute(
                query, [start.to_pydatetime(), end.to_pydatetime()]
            ).df()

    def _feature_context(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.DataFrame:
        frame = self._query_time_window(
            self.context_path,
            "strategy_candle_open_time",
            start,
            end,
        )
        if not frame.empty:
            frame["strategy_candle_open_time"] = pd.to_datetime(
                frame["strategy_candle_open_time"], utc=True, errors="coerce"
            )
        return frame

    def _signals(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        frame = self._query_time_window(
            self.signals_path,
            "candle_open_time",
            start,
            end,
        )
        if not frame.empty:
            frame["candle_open_time"] = pd.to_datetime(
                frame["candle_open_time"], utc=True, errors="coerce"
            )
        return frame

    def _sr_zone_inventory(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.DataFrame:
        frame = self._query_time_window(
            self.sr_zones_path,
            "strategy_candle_open_time",
            start,
            end,
        )
        if not frame.empty:
            frame["strategy_candle_open_time"] = pd.to_datetime(
                frame["strategy_candle_open_time"], utc=True, errors="coerce"
            )
            if "sr_completed_candle_time" in frame.columns:
                frame["sr_completed_candle_time"] = pd.to_datetime(
                    frame["sr_completed_candle_time"], utc=True, errors="coerce"
                )
            frame = self._expand_sr_snapshot_frame(frame)
            if not frame.empty:
                frame["strategy_candle_open_time"] = pd.to_datetime(
                    frame["strategy_candle_open_time"], utc=True, errors="coerce"
                )
                if "sr_completed_candle_time" in frame.columns:
                    frame["sr_completed_candle_time"] = pd.to_datetime(
                        frame["sr_completed_candle_time"], utc=True, errors="coerce"
                    )
        return frame

    def _inventory_sr_zones(
        self,
        inventory: pd.DataFrame,
        *,
        visible_start: pd.Timestamp,
        visible_end: pd.Timestamp,
        entry_snapshot: pd.Timestamp | None,
    ) -> list[dict[str, Any]]:
        """Compact full per-candle inventory into visual zone lifespans."""
        if inventory.empty:
            return []
        frame = inventory.copy()
        frame = frame.loc[
            frame["strategy_candle_open_time"] >= visible_start
        ].sort_values(
            ["sr_timeframe_minutes", "zone_id", "strategy_index"],
            kind="stable",
        )
        if frame.empty:
            return []

        interval = pd.Timedelta(
            interval_to_timedelta(self.seed.request.strategy_timeframe)
        )
        entry = _utc(entry_snapshot) if entry_snapshot is not None else None
        zones: list[dict[str, Any]] = []

        group_columns = [
            "sr_timeframe",
            "zone_id",
            "structure",
            "zone_low",
            "zone_high",
        ]
        for keys, group in frame.groupby(group_columns, sort=False, dropna=False):
            label, zone_id, structure, zone_low, zone_high = keys
            if label not in SR_TIMEFRAMES:
                continue
            group = group.sort_values("strategy_index", kind="stable").reset_index(
                drop=True
            )
            cursor = 0
            while cursor < len(group):
                end = cursor + 1
                while end < len(group):
                    prior_index = int(group.iloc[end - 1]["strategy_index"])
                    next_index = int(group.iloc[end]["strategy_index"])
                    if next_index != prior_index + 1:
                        break
                    end += 1

                segment = group.iloc[cursor:end]
                first = segment.iloc[0]
                last = segment.iloc[-1]
                start_time = _utc(first["strategy_candle_open_time"])
                end_time = _utc(last["strategy_candle_open_time"]) + interval
                active_at_entry = bool(
                    entry is not None and start_time <= entry < end_time
                )
                entry_row = None
                if active_at_entry:
                    eligible = segment.loc[
                        pd.to_datetime(
                            segment["strategy_candle_open_time"], utc=True
                        )
                        <= entry
                    ]
                    if not eligible.empty:
                        entry_row = eligible.iloc[-1]
                active_at_end = bool(end_time >= visible_end)

                zones.append(
                    {
                        "name": (
                            f"{SR_TIMEFRAMES[str(label)]} "
                            f"{str(structure).title()}"
                        ),
                        "kind": "sr-zone",
                        "timeframe": str(label),
                        "structure": str(structure).lower(),
                        "zoneIdentity": ["inventory", str(zone_id)],
                        "start": _unix_seconds(start_time),
                        "end": _unix_seconds(min(end_time, visible_end)),
                        "low": float(zone_low),
                        "high": float(zone_high),
                        "stateEnd": _json_value(last.get("state")),
                        "stateAtEntry": (
                            _json_value(entry_row.get("state"))
                            if entry_row is not None
                            else None
                        ),
                        "activeAtEntry": active_at_entry,
                        "activeAtEnd": active_at_end,
                        "nearestAtEntry": (
                            bool(entry_row.get("nearest"))
                            if entry_row is not None
                            else False
                        ),
                        "nearestAtEnd": (
                            bool(last.get("nearest")) if active_at_end else False
                        ),
                        "nearAtEnd": bool(last.get("near")),
                        "insideAtEnd": bool(last.get("inside")),
                        "testCountEnd": _json_value(last.get("test_count")),
                        "touchCountEnd": _json_value(last.get("touch_count")),
                        "sourceCountEnd": _json_value(last.get("source_count")),
                        "validationRejectionAtrEnd": _finite(
                            last.get("validation_rejection_atr")
                        ),
                        "rejectionAtrEnd": _finite(last.get("rejection_atr")),
                        "inventoryFull": True,
                    }
                )
                cursor = end

        zones.sort(
            key=lambda item: (
                item["timeframe"],
                item["structure"],
                item["start"],
                item["low"],
            )
        )
        return zones

    @staticmethod
    def _inventory_sr_lifecycle_events(
        inventory: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        """Show TEST/HELD transitions for every persisted active zone."""
        if inventory.empty:
            return []
        events: list[dict[str, Any]] = []
        grouped = inventory.sort_values(
            ["sr_timeframe_minutes", "zone_id", "strategy_index"],
            kind="stable",
        ).groupby(["sr_timeframe", "zone_id", "structure"], sort=False)
        for (label, _zone_id, structure), group in grouped:
            if label not in SR_TIMEFRAMES:
                continue
            prior_test = None
            prior_held = False
            prior_index = None
            for _, row in group.iterrows():
                current_index = int(row.get("strategy_index"))
                if prior_index is not None and current_index != prior_index + 1:
                    prior_test = None
                    prior_held = False
                prior_index = current_index
                test_count = int(row.get("test_count") or 0)
                held = bool(row.get("held"))
                event = None
                if prior_test is not None and test_count > prior_test:
                    event = "TEST"
                if held and not prior_held:
                    event = "HELD"
                prior_test = test_count
                prior_held = held
                if event is None:
                    continue
                events.append(
                    {
                        "time": _unix_seconds(row["strategy_candle_open_time"]),
                        "position": (
                            "belowBar"
                            if str(structure).upper() == "SUPPORT"
                            else "aboveBar"
                        ),
                        "shape": "circle" if event == "TEST" else "square",
                        "text": (
                            f"{SR_TIMEFRAMES[str(label)]} "
                            f"{str(structure)[0].upper()} {event}"
                        ),
                        "kind": "sr-event",
                        "event": event.lower(),
                        "timeframe": str(label),
                        "structure": str(structure).lower(),
                    }
                )
        events.sort(
            key=lambda item: (
                int(item["time"]),
                item["timeframe"],
                item["structure"],
            )
        )
        return events


    @staticmethod
    def _sr_frame_column(
        frame: pd.DataFrame, label: str, suffix: str
    ) -> str | None:
        preferred = f"sr_{label}_{suffix}"
        if preferred in frame.columns:
            return preferred
        if label == "strategy" and suffix in frame.columns:
            return suffix
        return None

    @classmethod
    def _sr_zone_identity(
        cls,
        frame: pd.DataFrame,
        row: Mapping[str, Any],
        id_column: str | None,
        low_column: str,
        high_column: str,
    ):
        identity = row.get(id_column) if id_column else None
        try:
            if identity is not None and not pd.isna(identity):
                return ("pivot", int(identity))
        except (TypeError, ValueError):
            pass
        low = _finite(row.get(low_column))
        high = _finite(row.get(high_column))
        if low is None or high is None:
            return None
        return ("zone", round(low, 12), round(high, 12))

    @classmethod
    def _sr_zones(
        cls,
        context: pd.DataFrame,
        label: str,
        visible_start: pd.Timestamp,
        entry_snapshot: pd.Timestamp | None = None,
    ) -> list[dict[str, Any]]:
        """Emit persisted S/R as shaded structural lifespans, never zig-zag lines."""
        if context.empty:
            return []
        frame = context.loc[
            context["strategy_candle_open_time"] >= visible_start
        ].copy()
        if frame.empty:
            return []
        frame = frame.sort_values(
            "strategy_candle_open_time", kind="stable"
        ).reset_index(drop=True)
        times = pd.DatetimeIndex(
            pd.to_datetime(frame["strategy_candle_open_time"], utc=True, errors="coerce")
        )
        if times.empty:
            return []
        interval = (
            pd.Timedelta(int(np.median(np.diff(times.asi8))), unit="ns")
            if len(times) > 1
            else pd.Timedelta(minutes=1)
        )
        entry = _utc(entry_snapshot) if entry_snapshot is not None else None

        zones: list[dict[str, Any]] = []
        for structure in ("support", "resistance"):
            low_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_zone_low"
            )
            high_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_zone_high"
            )
            if not low_column or not high_column:
                continue
            id_column = cls._sr_frame_column(
                frame, label, f"long_nearest_{structure}_bar_index"
            )
            state_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_state"
            )
            near_column = cls._sr_frame_column(
                frame, label, f"long_near_{structure}"
            )
            inside_column = cls._sr_frame_column(
                frame, label, f"long_inside_{structure}_zone"
            )
            tests_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_test_count"
            )
            rejection_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_rejection_atr"
            )
            conflict_column = cls._sr_frame_column(
                frame, label, "long_structure_conflict"
            )

            cursor = 0
            while cursor < len(frame):
                row = frame.iloc[cursor]
                identity = cls._sr_zone_identity(
                    frame, row, id_column, low_column, high_column
                )
                low = _finite(row.get(low_column))
                high = _finite(row.get(high_column))
                if identity is None or low is None or high is None:
                    cursor += 1
                    continue

                end = cursor + 1
                while end < len(frame):
                    next_row = frame.iloc[end]
                    next_identity = cls._sr_zone_identity(
                        frame, next_row, id_column, low_column, high_column
                    )
                    next_low = _finite(next_row.get(low_column))
                    next_high = _finite(next_row.get(high_column))
                    if (
                        next_identity != identity
                        or next_low is None
                        or next_high is None
                        or abs(next_low - low) > 1e-9
                        or abs(next_high - high) > 1e-9
                    ):
                        break
                    end += 1

                start_time = times[cursor]
                end_time = times[end] if end < len(times) else times[-1] + interval
                final_row = frame.iloc[end - 1]
                entry_row = None
                active_at_entry = False
                if entry is not None and start_time <= entry < end_time:
                    active_at_entry = True
                    eligible = [
                        i
                        for i in range(cursor, end)
                        if times[i] <= entry
                    ]
                    if eligible:
                        entry_row = frame.iloc[eligible[-1]]
                conflict = (
                    bool(final_row.get(conflict_column))
                    if conflict_column
                    else bool(final_row.get(near_column))
                    and bool(
                        final_row.get(
                            cls._sr_frame_column(
                                frame,
                                label,
                                "long_near_resistance"
                                if structure == "support"
                                else "long_near_support",
                            )
                        )
                    )
                )
                zones.append(
                    {
                        "name": f"{SR_TIMEFRAMES[label]} {structure.title()}",
                        "kind": "sr-zone",
                        "timeframe": label,
                        "structure": structure,
                        "zoneIdentity": list(identity),
                        "start": _unix_seconds(start_time),
                        "end": _unix_seconds(end_time),
                        "low": low,
                        "high": high,
                        "stateEnd": (
                            _json_value(final_row.get(state_column))
                            if state_column
                            else None
                        ),
                        "stateAtEntry": (
                            _json_value(entry_row.get(state_column))
                            if entry_row is not None and state_column
                            else None
                        ),
                        "activeAtEntry": active_at_entry,
                        "activeAtEnd": end == len(frame),
                        "nearestAtEntry": active_at_entry,
                        "nearestAtEnd": end == len(frame),
                        "nearAtEnd": bool(final_row.get(near_column))
                        if near_column
                        else False,
                        "insideAtEnd": bool(final_row.get(inside_column))
                        if inside_column
                        else False,
                        "testCountEnd": _json_value(final_row.get(tests_column))
                        if tests_column
                        else None,
                        "rejectionAtrEnd": _finite(final_row.get(rejection_column))
                        if rejection_column
                        else None,
                        "structureConflictEnd": conflict,
                    }
                )
                cursor = end
        return zones

    @classmethod
    def _sr_lifecycle_events(
        cls,
        context: pd.DataFrame,
        label: str,
        visible_start: pd.Timestamp,
    ) -> list[dict[str, Any]]:
        """Derive display-only lifecycle markers from persisted state transitions."""
        if context.empty:
            return []
        frame = context.loc[
            context["strategy_candle_open_time"] >= visible_start
        ].copy()
        if frame.empty:
            return []
        frame = frame.sort_values(
            "strategy_candle_open_time", kind="stable"
        ).reset_index(drop=True)
        times = pd.to_datetime(
            frame["strategy_candle_open_time"], utc=True, errors="coerce"
        )
        events: list[dict[str, Any]] = []

        for structure in ("support", "resistance"):
            low_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_zone_low"
            )
            high_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_zone_high"
            )
            if not low_column or not high_column:
                continue
            id_column = cls._sr_frame_column(
                frame, label, f"long_nearest_{structure}_bar_index"
            )
            state_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_state"
            )
            test_count_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_test_count"
            )
            held_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_held"
            )
            break_column = cls._sr_frame_column(
                frame, label, f"long_{structure}_last_break_index"
            )
            previous_by_identity: dict[tuple, dict[str, Any]] = {}
            previous_break = object()

            for index, raw in frame.iterrows():
                timestamp = times.iloc[index]
                if pd.isna(timestamp):
                    continue
                identity = cls._sr_zone_identity(
                    frame, raw, id_column, low_column, high_column
                )
                event = None
                state = _json_value(raw.get(state_column)) if state_column else None
                test_count = (
                    _finite(raw.get(test_count_column))
                    if test_count_column
                    else None
                )
                held = bool(raw.get(held_column)) if held_column else False

                break_value = (
                    _json_value(raw.get(break_column)) if break_column else None
                )
                if break_value is not None and break_value != previous_break:
                    if index > 0:
                        event = "BREAK"
                    previous_break = break_value
                elif break_value is None and index == 0:
                    previous_break = None

                if identity is not None:
                    previous = previous_by_identity.get(identity)
                    if previous is not None and event is None:
                        if held and not previous["held"]:
                            event = "HELD"
                        elif (
                            test_count is not None
                            and previous["test_count"] is not None
                            and test_count > previous["test_count"]
                        ):
                            event = "TEST"
                        elif (
                            state is not None
                            and state != previous["state"]
                            and str(state).endswith("_TESTING")
                        ):
                            event = "TEST"
                    previous_by_identity[identity] = {
                        "held": held,
                        "test_count": test_count,
                        "state": state,
                    }

                if event is not None:
                    events.append(
                        {
                            "time": _unix_seconds(timestamp),
                            "position": (
                                "belowBar" if structure == "support" else "aboveBar"
                            ),
                            "shape": "circle" if event == "TEST" else "square",
                            "text": f"{SR_TIMEFRAMES[label]} {structure[0].upper()} {event}",
                            "kind": "sr-event",
                            "event": event.lower(),
                            "timeframe": label,
                            "structure": structure,
                        }
                    )
        events.sort(key=lambda item: (item["time"], item["timeframe"], item["structure"]))
        return events

    def _overlays(
        self,
        market: pd.DataFrame,
        context: pd.DataFrame,
        visible_start: pd.Timestamp,
        *,
        chart_timeframe: str | None = None,
    ) -> list[dict[str, Any]]:
        overlays: list[dict[str, Any]] = []
        if market.empty:
            return overlays
        market_times = market["period_start"]
        visible_mask = market_times >= visible_start
        visible_times = market_times[visible_mask]

        for period in (50, 100, 200):
            values = _ema(market["close"], period)
            data = _line_points(visible_times, values[visible_mask.to_numpy()])
            if data:
                overlays.append(
                    {
                        "name": f"EMA {period}",
                        "kind": "ema",
                        "period": period,
                        "data": data,
                    }
                )

        strategy_timeframe = str(self.seed.request.strategy_timeframe)
        selected_chart_timeframe = str(chart_timeframe or strategy_timeframe)
        if not context.empty and selected_chart_timeframe == strategy_timeframe:
            times = context["strategy_candle_open_time"]
            mask = times >= visible_start
            for column, name, kind in (
                ("session_vwap", "VWAP", "vwap"),
                ("bb_middle", "BB Middle", "bb"),
                ("bb_upper", "BB Upper", "bb"),
                ("bb_lower", "BB Lower", "bb"),
            ):
                if column in context.columns:
                    data = _line_points(times[mask], context.loc[mask, column])
                    if data:
                        overlays.append({"name": name, "kind": kind, "data": data})
        return overlays

    @staticmethod
    def _context_by_time(
        context: pd.DataFrame, visible_start: pd.Timestamp
    ) -> dict[str, dict[str, Any]]:
        if context.empty:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for _, row in context.iterrows():
            timestamp = _utc(row["strategy_candle_open_time"])
            if timestamp < visible_start:
                continue
            facts = _categorical_context(row)
            if facts:
                result[str(_unix_seconds(timestamp))] = facts
        return result

    @staticmethod
    def _snap_to_candle(timestamp: Any, market: pd.DataFrame) -> int | None:
        target = _utc(timestamp)
        times = pd.DatetimeIndex(pd.to_datetime(market["period_start"], utc=True))
        if times.empty:
            return None
        if target < times[0]:
            return None
        interval_ns = (
            int(np.median(np.diff(times.asi8)))
            if len(times) > 1
            else int(pd.Timedelta(minutes=1).value)
        )
        if target.value >= times[-1].value + max(1, interval_ns):
            return None
        index = int(np.searchsorted(times.asi8, target.value, side="right") - 1)
        index = max(0, min(index, len(times) - 1))
        return _unix_seconds(times[index])

    def _markers(
        self,
        signals: pd.DataFrame,
        trade_index: int | None,
        show_rejections: bool,
        market: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        markers: list[dict[str, Any]] = []
        if not signals.empty:
            for _, row in signals.iterrows():
                decision = str(row.get("decision") or "").upper()
                if decision == "REJECT" and not show_rejections:
                    continue
                side = str(row.get("side") or "").upper()
                snapped = self._snap_to_candle(row["candle_open_time"], market)
                if snapped is None:
                    continue
                marker = {
                    "time": snapped,
                    "position": "belowBar" if side == "LONG" else "aboveBar",
                    "shape": (
                        "arrowUp"
                        if decision == "ENTER" and side == "LONG"
                        else "arrowDown"
                        if decision == "ENTER" and side == "SHORT"
                        else "circle"
                    ),
                    "text": (
                        "ENTRY"
                        if decision == "ENTER"
                        else f"REJECT · {str(row.get('reason_code') or '')[:48]}"
                    ),
                    "kind": decision.lower(),
                }
                markers.append(marker)

        if trade_index is not None and self.trade_count:
            row = self._trade_row(trade_index)
            side = _trade_side(row)
            exit_time = row.get("exit_time")
            if exit_time is not None and not pd.isna(exit_time):
                reason = _first_value(
                    row,
                    (
                        f"{side.lower()}_final_exit_reason",
                        f"{side.lower()}_exit_reason",
                        "exit_reason",
                    ),
                )
                snapped = self._snap_to_candle(exit_time, market)
                if snapped is not None:
                    markers.append(
                        {
                            "time": snapped,
                            "position": "aboveBar" if side == "LONG" else "belowBar",
                            "shape": "square",
                            "text": f"EXIT · {reason or ''}".strip(),
                            "kind": "exit",
                        }
                    )
        markers.sort(key=lambda item: (int(item["time"]), str(item.get("kind", ""))))
        return markers

    def _snap_timed_items_to_market(
        self,
        items: list[dict[str, Any]],
        market: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        """Snap strategy-timeline visual events onto the selected chart candles."""
        result: list[dict[str, Any]] = []
        for item in items:
            timestamp = item.get("time")
            if timestamp is None:
                continue
            snapped = self._snap_to_candle(
                pd.Timestamp(int(timestamp), unit="s", tz="UTC"),
                market,
            )
            if snapped is None:
                continue
            copy = dict(item)
            copy["time"] = snapped
            result.append(copy)
        result.sort(
            key=lambda item: (
                int(item["time"]),
                str(item.get("timeframe", "")),
                str(item.get("structure", "")),
                str(item.get("event", "")),
            )
        )
        return result

    def _price_lines(self, trade_index: int | None) -> list[dict[str, Any]]:
        if trade_index is None or not self.trade_count:
            return []
        row = self._trade_row(trade_index)
        stop, target = trade_stop_target(row)
        entry = _finite(
            _first_value(row, ("entry_price", "actual_entry_price", "strategy_entry_price"))
        )
        result = []
        for title, value, kind in (
            ("Entry", entry, "entry"),
            ("Stop", stop, "stop"),
            ("Target", target, "target"),
        ):
            if value is not None:
                result.append({"title": title, "price": value, "kind": kind})
        return result

    def build_payload(
        self,
        *,
        trade_index: int | None = None,
        visible_candles: int = DEFAULT_VISIBLE_CANDLES,
        show_rejections: bool = False,
        full_run: bool = False,
        chart_timeframe: str | None = None,
    ) -> dict[str, Any]:
        if self.trade_count:
            if trade_index is None:
                trade_index = 0
            trade_index = max(0, min(self.trade_count - 1, int(trade_index)))
        else:
            trade_index = None

        strategy_timeframe = str(self.seed.request.strategy_timeframe)
        chart_timeframe = str(chart_timeframe or strategy_timeframe)
        available_timeframes = self.available_chart_timeframes()
        available_intervals = {
            str(item.get("interval"))
            for item in available_timeframes
        }
        if chart_timeframe not in available_intervals:
            raise ValueError(
                f"chart timeframe {chart_timeframe!r} is not available in the canonical Data Lake "
                f"for {self.seed.request.symbol}; available={sorted(available_intervals)}"
            )

        calculation_start, visible_start, visible_end = self._window_bounds(
            trade_index,
            visible_candles,
            full_run=full_run,
            chart_timeframe=chart_timeframe,
        )
        market = self._market_frame(
            calculation_start,
            visible_end,
            chart_timeframe=chart_timeframe,
        )
        if market.empty:
            raise ValueError("no canonical strategy candles are available for this chart window")
        context = self._feature_context(visible_start, visible_end)
        signals = self._signals(visible_start, visible_end)
        zone_inventory = self._sr_zone_inventory(visible_start, visible_end)

        visible = market[
            (market["period_start"] >= visible_start)
            & (market["period_start"] < visible_end)
        ].copy()
        candles = []
        for _, row in visible.iterrows():
            candles.append(
                {
                    "time": _unix_seconds(row["period_start"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
            )
        entry_snapshot = self.selected_trade_candle_time(trade_index)
        entry_chart_snapshot = (
            self._snap_to_candle(entry_snapshot, visible)
            if entry_snapshot is not None
            else None
        )
        sr_zones: list[dict[str, Any]] = []
        sr_events: list[dict[str, Any]] = []
        if not zone_inventory.empty:
            sr_zones = self._inventory_sr_zones(
                zone_inventory,
                visible_start=visible_start,
                visible_end=visible_end,
                entry_snapshot=entry_snapshot,
            )
            sr_events = self._inventory_sr_lifecycle_events(zone_inventory)
            if not context.empty:
                # Broken zones are retired from the active inventory immediately.
                # Preserve causal BREAK markers from the nearest-context lifecycle.
                for label in SR_TIMEFRAMES:
                    sr_events.extend(
                        event
                        for event in self._sr_lifecycle_events(
                            context, label, visible_start
                        )
                        if event.get("event") == "break"
                    )
            sr_events = sorted(
                {
                    (
                        int(event["time"]),
                        str(event.get("timeframe")),
                        str(event.get("structure")),
                        str(event.get("event")),
                    ): event
                    for event in sr_events
                }.values(),
                key=lambda item: (
                    int(item["time"]),
                    str(item.get("timeframe")),
                    str(item.get("structure")),
                ),
            )
            sr_events = self._snap_timed_items_to_market(sr_events, visible)
        elif not context.empty:
            # Legacy completed runs contain nearest-zone context only.
            for label in SR_TIMEFRAMES:
                sr_zones.extend(
                    self._sr_zones(
                        context, label, visible_start, entry_snapshot=entry_snapshot
                    )
                )
                sr_events.extend(
                    self._sr_lifecycle_events(context, label, visible_start)
                )
            sr_events = self._snap_timed_items_to_market(sr_events, visible)

        request = self.seed.request
        return {
            "run": {
                "runId": str(self.manifest.get("run_id") or self.run_dir.name),
                "symbol": request.symbol,
                "timeframe": request.strategy_timeframe,
                "strategyTimeframe": strategy_timeframe,
                "chartTimeframe": chart_timeframe,
                "chartSourceMode": (
                    "completed-run-provenance"
                    if chart_timeframe == strategy_timeframe
                    else "current-canonical-cache-reference"
                ),
                "availableChartTimeframes": available_timeframes,
                "start": _utc(request.period_start).isoformat(),
                "end": _utc(request.period_end).isoformat(),
                "sourceVerified": self.source_verified,
                "ruleTraceAvailable": self.rule_trace_path is not None,
                "srZoneInventoryAvailable": self.sr_zones_path is not None,
            },
            "selectedTradeIndex": trade_index,
            "selectedTrade": self.selected_trade_summary(trade_index),
            "selectedTradeCandleTime": (
                _unix_seconds(entry_snapshot) if entry_snapshot is not None else None
            ),
            "selectedTradeChartCandleTime": entry_chart_snapshot,
            "candles": candles,
            "overlays": self._overlays(
                market,
                context,
                visible_start,
                chart_timeframe=chart_timeframe,
            ),
            "srZones": sr_zones,
            "srEvents": sr_events,
            "markers": self._markers(signals, trade_index, show_rejections, visible),
            "priceLines": self._price_lines(trade_index),
            "candleContext": self._context_by_time(context, visible_start),
            "visibleStart": _unix_seconds(visible_start),
            "visibleEnd": _unix_seconds(visible_end),
            "fullRun": bool(full_run),
            "chartTimeframe": chart_timeframe,
        }


def build_visualizer_html(payload: Mapping[str, Any]) -> str:
    """Build one self-contained chart page around a bounded run payload."""
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
html,body{{height:100%;margin:0;background:#0f1720;color:#e6edf3;font-family:Segoe UI,Arial,sans-serif;overflow:hidden}}
#root{{height:100%;display:grid;grid-template-rows:1fr auto;min-height:0}}
#chart-wrap{{position:relative;min-height:0}}
#chart{{position:absolute;inset:0;z-index:1}}
#zone-layer,#zone-label-layer{{position:absolute;inset:0;pointer-events:none;overflow:hidden}}
#zone-layer{{z-index:2}}
#zone-label-layer{{z-index:4}}
.zone-band{{position:absolute;box-sizing:border-box;border-radius:2px}}
.zone-label{{position:absolute;right:66px;max-width:220px;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:600;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.35)}}
.zone-label.support{{background:rgba(33,92,68,.92);color:#c7f4de;border:1px solid rgba(111,211,164,.55)}}
.zone-label.resistance{{background:rgba(107,52,52,.92);color:#ffd1d1;border:1px solid rgba(240,138,138,.55)}}
#readout{{position:absolute;left:10px;top:8px;z-index:5;pointer-events:none;background:rgba(15,23,32,.82);border:1px solid #334155;border-radius:5px;padding:7px 9px;font-size:12px;line-height:1.45;max-width:64%;white-space:normal}}
#facts{{font-size:11px;color:#b8c2cc;margin-top:3px}}
#footer{{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:5px 9px;border-top:1px solid #263241;color:#8f9baa;font-size:11px}}
#footer a{{color:#a9c8ff;text-decoration:none}}
#error{{position:absolute;inset:20px;display:none;place-items:center;text-align:center;color:#ffb4b4}}
</style>
<script src="{LIGHTWEIGHT_CHARTS_URL}"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
</head>
<body>
<div id="root">
  <div id="chart-wrap">
    <div id="chart"></div>
    <div id="zone-layer"></div>
    <div id="zone-label-layer"></div>
    <div id="readout">Click a candle to inspect causal evidence.</div>
    <div id="error"></div>
  </div>
  <div id="footer">
    <span>Completed-run view · no strategy re-evaluation</span>
    <span>Charting by <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></span>
  </div>
</div>
<script>
(() => {{
  const payload = {encoded};
  const error = document.getElementById('error');
  const readout = document.getElementById('readout');
  if (!window.LightweightCharts) {{
    error.style.display='grid';
    error.textContent='Chart library could not be loaded. Check internet access and reopen Strategy Visualizer.';
    return;
  }}
  let strategyBridge = null;
  if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {{
    new QWebChannel(window.qt.webChannelTransport, channel => {{
      strategyBridge = channel.objects.strategyBridge || null;
    }});
  }}
  const LC = window.LightweightCharts;
  const chart = LC.createChart(document.getElementById('chart'), {{
    autoSize: true,
    attributionLogo: true,
    layout: {{ background: {{ type: 'solid', color: '#0f1720' }}, textColor: '#b8c2cc' }},
    grid: {{ vertLines: {{ color: '#1d2937' }}, horzLines: {{ color: '#1d2937' }} }},
    rightPriceScale: {{ borderColor: '#334155' }},
    timeScale: {{ borderColor: '#334155', timeVisible: true, secondsVisible: false, rightOffset: 10 }},
    crosshair: {{ mode: 0 }},
  }});
  const candle = chart.addSeries(LC.CandlestickSeries, {{
    upColor:'#22a06b', downColor:'#d84a4a', borderVisible:false,
    wickUpColor:'#22a06b', wickDownColor:'#d84a4a',
  }});
  candle.setData(payload.candles || []);

  const seriesStyles = {{
    ema: {{ lineWidth: 1, color:'#8fb4ff' }},
    vwap: {{ lineWidth: 1, color:'#d5a94b' }},
    bb: {{ lineWidth: 1, color:'#8a94a3', lineStyle:2 }},
    sr: {{ lineWidth: 1, color:'#9da8b5', lineStyle:2 }},
  }};
  for (const overlay of payload.overlays || []) {{
    const style = {{...(seriesStyles[overlay.kind] || seriesStyles.sr)}};
    if (overlay.kind === 'sr' && overlay.name.includes('Support')) style.color='#4baa7b';
    if (overlay.kind === 'sr' && overlay.name.includes('Resistance')) style.color='#ce6a6a';
    const line = chart.addSeries(LC.LineSeries, {{
      ...style, title: overlay.name, priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:false,
    }});
    line.setData(overlay.data || []);
  }}

  const chartWrap = document.getElementById('chart-wrap');
  const zoneLayer = document.getElementById('zone-layer');
  const zoneLabelLayer = document.getElementById('zone-label-layer');
  const review = payload.srReview || {{ mode:'normal', snapshot:'live', details:'zones' }};

  function activeForReference(zone) {{
    return review.snapshot === 'entry'
      ? Boolean(zone.activeAtEntry)
      : Boolean(zone.activeAtEnd);
  }}
  function nearestForReference(zone) {{
    if (review.snapshot === 'entry')
      return zone.nearestAtEntry === undefined
        ? Boolean(zone.activeAtEntry)
        : Boolean(zone.nearestAtEntry);
    return zone.nearestAtEnd === undefined
      ? Boolean(zone.activeAtEnd)
      : Boolean(zone.nearestAtEnd);
  }}
  function xForTime(time, startSide) {{
    const direct = chart.timeScale().timeToCoordinate(time);
    if (direct !== null && direct !== undefined) return direct;
    const range = chart.timeScale().getVisibleRange();
    if (!range) return null;
    if (Number(time) <= Number(range.from)) return 0;
    if (Number(time) >= Number(range.to)) return chartWrap.clientWidth;
    return startSide ? 0 : chartWrap.clientWidth;
  }}
  function shortState(value) {{
    return String(value || '')
      .replace('SUPPORT_', '')
      .replace('RESISTANCE_', '')
      .replaceAll('_', ' ');
  }}
  function drawZones() {{
    zoneLayer.replaceChildren();
    zoneLabelLayer.replaceChildren();
    const labels = [];
    for (const zone of payload.srZones || []) {{
      const frozenEntryZone = (
        review.mode === 'review'
        && review.snapshot === 'entry'
        && Boolean(zone.activeAtEntry)
      );
      const drawStart = frozenEntryZone
        ? Math.max(Number(zone.start), Number(payload.selectedTradeCandleTime || zone.start))
        : zone.start;
      const drawEnd = frozenEntryZone ? payload.visibleEnd : zone.end;
      const x1 = xForTime(drawStart, true);
      const x2 = xForTime(drawEnd, false);
      const yHigh = candle.priceToCoordinate(Number(zone.high));
      const yLow = candle.priceToCoordinate(Number(zone.low));
      if ([x1,x2,yHigh,yLow].some(v => v === null || v === undefined || !Number.isFinite(Number(v)))) continue;

      const active = activeForReference(zone);
      const nearest = nearestForReference(zone);
      const snapshotDim = review.mode === 'review' && review.snapshot === 'entry' && !active;
      const baseAlpha = review.mode === 'review'
        ? (nearest ? 0.24 : active ? 0.11 : snapshotDim ? 0.018 : 0.045)
        : (nearest ? 0.13 : active ? 0.07 : 0.035);
      const support = zone.structure === 'support';
      const fill = support
        ? `rgba(53, 180, 119, ${{baseAlpha}})`
        : `rgba(220, 90, 90, ${{baseAlpha}})`;
      const border = support
        ? `rgba(86, 214, 151, ${{Math.min(.75, baseAlpha + .28)}})`
        : `rgba(238, 120, 120, ${{Math.min(.75, baseAlpha + .28)}})`;

      const band = document.createElement('div');
      band.className = 'zone-band';
      band.style.left = Math.min(x1,x2) + 'px';
      band.style.width = Math.max(2, Math.abs(x2-x1)) + 'px';
      band.style.top = Math.min(yHigh,yLow) + 'px';
      band.style.height = Math.max(2, Math.abs(yLow-yHigh)) + 'px';
      band.style.background = fill;
      band.style.borderTop = '1px solid ' + border;
      band.style.borderBottom = '1px solid ' + border;
      zoneLayer.appendChild(band);

      if (nearest) {{
        const state = review.snapshot === 'entry'
          ? zone.stateAtEntry
          : zone.stateEnd;
        labels.push({{
          top: (Number(yHigh) + Number(yLow))/2 - 10,
          structure: zone.structure,
          text: zone.name + (state ? ' · ' + shortState(state) : ''),
        }});
      }}
    }}
    labels.sort((a,b) => a.top-b.top);
    let lastTop = -999;
    for (const item of labels) {{
      const top = Math.max(4, item.top <= lastTop + 20 ? lastTop + 22 : item.top);
      lastTop = top;
      const label = document.createElement('div');
      label.className = 'zone-label ' + item.structure;
      label.style.top = top + 'px';
      label.textContent = item.text;
      zoneLabelLayer.appendChild(label);
    }}
  }}

  if (LC.createSeriesMarkers) {{
    const markerSource = [
      ...(payload.markers || []),
      ...(payload.srEvents || []),
    ];
    if (
      review.mode === 'review'
      && review.snapshot === 'entry'
      && payload.selectedTradeCandleTime
    ) {{
      markerSource.push({{
        time: payload.selectedTradeCandleTime,
        position: 'belowBar',
        shape: 'circle',
        text: 'S/R SNAPSHOT',
        kind: 'sr-snapshot',
      }});
    }}
    markerSource.sort((a,b) => Number(a.time)-Number(b.time));
    const markers=markerSource.map(m => ({{
      time:m.time, position:m.position, shape:m.shape, text:m.text,
      color: m.kind==='entry' ? '#6fd3a4'
        : m.kind==='exit' ? '#ffd166'
        : m.kind==='sr-snapshot' ? '#9ec5ff'
        : m.kind==='sr-event' && m.event==='break' ? '#ff8e8e'
        : m.kind==='sr-event' && m.event==='held' ? '#7ee2ac'
        : m.kind==='sr-event' ? '#d8b36a'
        : '#9aa5b1',
    }}));
    LC.createSeriesMarkers(candle, markers);
  }}

  for (const line of payload.priceLines || []) {{
    const color=line.kind==='entry' ? '#7db7ff' : line.kind==='stop' ? '#f08a8a' : '#79d39d';
    candle.createPriceLine({{
      price:line.price, color, lineWidth:2, lineStyle:2,
      axisLabelVisible:true, title:line.title,
    }});
  }}

  function fmt(n) {{
    return Number.isFinite(Number(n)) ? Number(n).toLocaleString(undefined, {{maximumFractionDigits:4}}) : '—';
  }}
  function showAt(time, bar) {{
    if (!time) return;
    const fact = (payload.candleContext || {{}})[String(time)] || {{}};
    const parts = Object.entries(fact).map(([k,v]) => k + ': ' + v);
    const ohlc = bar ? 'O ' + fmt(bar.open) + '  H ' + fmt(bar.high) + '  L ' + fmt(bar.low) + '  C ' + fmt(bar.close) : '';
    const stamp = new Date(Number(time)*1000).toISOString().replace('T',' ').slice(0,16) + ' UTC';
    readout.innerHTML = '<b>' + stamp + '</b>' + (ohlc ? '<br>' + ohlc : '') +
      (parts.length ? '<div id="facts">' + parts.join(' · ') + '</div>' : '');
  }}
  chart.subscribeClick(param => {{
    if (!param || !param.time) return;
    showAt(param.time, param.seriesData.get(candle));
    if (strategyBridge && strategyBridge.selectCandle)
      strategyBridge.selectCandle(String(param.time));
  }});
  chart.subscribeCrosshairMove(param => {{
    if (!param || !param.time || !param.seriesData.has(candle)) return;
    if (param.sourceEvent && param.sourceEvent.type === 'mousemove')
      showAt(param.time, param.seriesData.get(candle));
  }});
  chart.timeScale().fitContent();
  if (payload.visibleStart && payload.visibleEnd) {{
    chart.timeScale().setVisibleRange({{ from: payload.visibleStart, to: payload.visibleEnd }});
  }}
  chart.timeScale().subscribeVisibleTimeRangeChange(() => drawZones());
  if (window.ResizeObserver) {{
    new ResizeObserver(() => drawZones()).observe(chartWrap);
  }}
  requestAnimationFrame(() => drawZones());
}})();
</script>
</body>
</html>"""


__all__ = [
    "CompletedRunVisualizer",
    "DEFAULT_VISIBLE_CANDLES",
    "LIGHTWEIGHT_CHARTS_URL",
    "LIGHTWEIGHT_CHARTS_VERSION",
    "MAX_VISIBLE_CANDLES",
    "MIN_VISIBLE_CANDLES",
    "SR_TIMEFRAMES",
    "build_visualizer_html",
    "trade_stop_target",
]
