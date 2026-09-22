"""Causal opposite-side replay for symmetric teacher-loss FLIP research.

The normal walk-forward outcome firewall uses immutable Every Viable Entry (EVE)
rows.  A teacher loss can lack an opposite-side EVE row even though the completed
reference run was executed from immutable 1m intrabar data.  This module provides
one deliberately narrow fallback for that case:

* ATR risk only;
* fixed, symmetric 1:1 target/stop semantics;
* no partial exits, break-even, trailing, timeout, or dynamic S/R target;
* immutable reference-run source provenance must still match the local data lake;
* the hypothetical opposite trade may use candles only through the teacher
  trade's own resolution timestamp.

The last point preserves causal chronology.  If the hypothetical opposite trade
would resolve only later, its future result is not exposed at the teacher-loss
boundary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind, MarketKind
from crypto_strategy_lab.data.source_identity import canonical_partition_identity
from crypto_strategy_lab.data.store import MarketDataStore
from crypto_strategy_lab.run_manifest import artifact_path


REPLAY_SOURCE = "IMMUTABLE_1M_INTRABAR_REPLAY"


def _utc(value: Any, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError(f"{name} is missing")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _execution_profile(manifest: dict[str, Any], profile: str) -> dict[str, Any]:
    return dict(
        (((manifest.get("config") or {}).get("execution") or {}).get("profiles") or {}).get(
            str(profile).lower()
        )
        or {}
    )


def _validate_simple_one_r(manifest: dict[str, Any], profile: str) -> tuple[dict[str, Any], dict[str, Any]]:
    config = manifest.get("config") or {}
    data = config.get("data") or {}
    execution = config.get("execution") or {}
    values = _execution_profile(manifest, profile)
    if not values:
        raise ValueError(f"immutable reference config has no execution profile {profile}")
    if str(execution.get("risk_mode", "ATR")).upper() != "ATR":
        raise ValueError("opposite replay is limited to ATR-risk reference setups")
    if not bool(data.get("use_intrabar_data", False)):
        raise ValueError("reference run did not use intrabar execution")
    if int(data.get("intrabar_timeframe_minutes", 0) or 0) != 1:
        raise ValueError("opposite replay requires immutable 1m intrabar execution")
    ratio = float(values.get("reward_risk_ratio", 0.0) or 0.0)
    if abs(ratio - 1.0) > 1e-12:
        raise ValueError("opposite replay is limited to symmetric 1:1 R:R profiles")
    if str(execution.get("sr_take_profit_mode", "FIXED_R")).upper() != "FIXED_R":
        raise ValueError("opposite replay does not support dynamic S/R take-profit modes")
    unsupported = {
        "partial_stop_enabled": values.get("partial_stop_enabled", False),
        "partial_profit_enabled": values.get("partial_profit_enabled", False),
        "trailing_enabled": values.get("trailing_enabled", False),
        "break_even_enabled": values.get("break_even_enabled", False),
        "timeout_enabled": values.get("timeout_enabled", False),
        "r_step_trailing_enabled": values.get("r_step_trailing_enabled", False),
        "atr_checkpoint_tp_extension_enabled": values.get(
            "atr_checkpoint_tp_extension_enabled", False
        ),
    }
    enabled = [name for name, value in unsupported.items() if bool(value)]
    if enabled:
        raise ValueError(
            "opposite replay supports only simple fixed 1:1 exits; enabled: "
            + ", ".join(enabled)
        )
    return execution, values


def _teacher_trade_context(
    manifest: dict[str, Any],
    run_dir: Path,
    teacher: dict[str, Any],
    trade_context: dict[str, Any],
) -> dict[str, Any]:
    """Recover execution scalars from the immutable teacher trade when possible."""
    result = dict(trade_context)
    pair_id = teacher.get("pair_id")
    if pair_id in (None, "") or "trades" not in (manifest.get("artifacts") or {}):
        return result
    path = artifact_path(run_dir, manifest, "trades", verify=True)
    with duckdb.connect(":memory:") as connection:
        columns = {
            str(row[0])
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{str(path).replace(chr(39), chr(39) * 2)}')"
            ).fetchall()
        }
        wanted = [
            name
            for name in (
                "pair_id",
                "side",
                "strategy_profile_key",
                "entry_time",
                "entry_price",
                "atr_at_entry",
                "exit_time",
                "pair_net_r",
            )
            if name in columns
        ]
        if "pair_id" not in wanted:
            return result
        selected = ", ".join(f'"{name}"' for name in wanted)
        rows = connection.execute(
            f"SELECT {selected} FROM read_parquet('{str(path).replace(chr(39), chr(39) * 2)}') "
            "WHERE CAST(pair_id AS VARCHAR)=? LIMIT 3",
            [str(pair_id)],
        ).fetchall()
    if len(rows) != 1:
        return result
    immutable = dict(zip(wanted, rows[0]))
    for key, value in immutable.items():
        if value is not None:
            result[key] = value
    return result


def _overlaps(row_start: Any, row_end: Any, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    if row_start in (None, "") or row_end in (None, ""):
        return True
    left = _utc(row_start, "source period_start")
    right = _utc(row_end, "source period_end")
    return left < end and right > start


def _verified_intrabar_frame(
    control: Any,
    manifest: dict[str, Any],
    run_dir: Path,
    *,
    start: pd.Timestamp,
    end_inclusive: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load 1m execution bars only when their source identities match the reference run."""
    if not hasattr(control, "raw_root") or not hasattr(control, "cache_root"):
        raise ValueError("control service does not expose the immutable market-data roots")

    request_meta = manifest.get("request") or {}
    symbol = str(request_meta.get("symbol") or "").upper()
    if not symbol:
        raise ValueError("reference manifest has no symbol")
    interval = str(
        request_meta.get("effective_intrabar_interval")
        or request_meta.get("requested_intrabar_interval")
        or "1m"
    )
    if interval != "1m":
        raise ValueError("reference manifest did not execute on 1m intrabars")
    strategy_interval = str(
        request_meta.get("requested_strategy_interval")
        or f"{int((((manifest.get('config') or {}).get('data') or {}).get('strategy_timeframe_minutes', 0)))}m"
    )
    market_raw = str(request_meta.get("market") or MarketKind.FUTURES_UM.value)
    try:
        market = MarketKind(market_raw)
    except ValueError as exc:
        raise ValueError(f"unsupported immutable reference market: {market_raw}") from exc

    end = end_inclusive + pd.Timedelta(minutes=1)
    request = DataRequest(
        symbol=symbol,
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        strategy_interval=strategy_interval,
        intrabar_interval="1m",
        market=market,
    )
    store = MarketDataStore(Path(control.raw_root), Path(control.cache_root))
    store.refresh_catalog()
    records = store.catalog.records_for(
        store.raw_root, request, DatasetKind.KLINES, "1m"
    )
    if not records:
        raise ValueError("local data lake has no 1m kline coverage for the replay window")

    source_path = artifact_path(run_dir, manifest, "source_archives", verify=True)
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            f"SELECT canonical_partition_identity, period_start, period_end "
            f"FROM read_parquet('{str(source_path).replace(chr(39), chr(39) * 2)}') "
            "WHERE LOWER(CAST(dataset AS VARCHAR))='klines' "
            "AND CAST(interval AS VARCHAR)='1m' "
            "AND UPPER(CAST(symbol AS VARCHAR))=?",
            [symbol],
        ).fetchall()
    expected_ids = {
        str(identity)
        for identity, period_start, period_end in rows
        if identity not in (None, "") and _overlaps(period_start, period_end, start, end)
    }
    adapter = store._adapter_for(DatasetKind.KLINES)
    contract = adapter.canonical_contract()
    current_ids = {
        canonical_partition_identity(record, contract) for record in records
    }
    if not expected_ids:
        raise ValueError("reference provenance has no immutable 1m source partition for the replay window")
    if current_ids != expected_ids:
        raise ValueError(
            "local 1m source partitions do not match the immutable reference-run provenance"
        )

    frame = store.load_execution_klines(request, "1m")
    if frame.empty:
        raise ValueError("immutable 1m replay window contains no candles")
    times = pd.to_datetime(frame["period_start"], utc=True)
    frame = frame.copy()
    frame["period_start"] = times
    frame = frame[(frame["period_start"] >= start) & (frame["period_start"] <= end_inclusive)]
    if frame.empty or frame.iloc[0]["period_start"] != start:
        raise ValueError("immutable 1m replay does not begin at the teacher entry timestamp")
    diffs = frame["period_start"].diff().dropna()
    if bool((diffs > pd.Timedelta(minutes=1)).any()):
        raise ValueError("immutable 1m replay contains a candle gap")
    return frame.reset_index(drop=True), {
        "source_partition_count": len(current_ids),
        "source_provenance_verified": True,
        "intrabar_interval": "1m",
    }


def _simulate_simple_one_r(
    frame: pd.DataFrame,
    *,
    side: str,
    entry_price: float,
    stop_distance: float,
    account_r_distance: float | None = None,
    slippage: float,
    tie_policy: str,
    entry_fee_rate: float,
    exit_fee_rate: float,
) -> dict[str, Any] | None:
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("opposite replay side must be LONG or SHORT")
    if stop_distance <= 0:
        raise ValueError("opposite replay stop distance must be positive")
    r_denominator = (
        float(account_r_distance)
        if account_r_distance is not None
        else float(stop_distance)
    )
    if r_denominator <= 0:
        raise ValueError("opposite replay account-R distance must be positive")
    sign = 1.0 if side == "LONG" else -1.0
    stop_price = entry_price - sign * stop_distance
    target_price = entry_price + sign * stop_distance
    tie = str(tie_policy).upper()

    for _, row in frame.iterrows():
        high, low = float(row["high"]), float(row["low"])
        hit_tp = high >= target_price if side == "LONG" else low <= target_price
        hit_sl = low <= stop_price if side == "LONG" else high >= stop_price
        if not (hit_tp or hit_sl):
            continue
        ambiguous = bool(hit_tp and hit_sl)
        use_tp = (tie == "OPTIMISTIC") if ambiguous else bool(hit_tp)
        raw_exit = target_price if use_tp else stop_price
        execution_exit = raw_exit * (1.0 - slippage if side == "LONG" else 1.0 + slippage)
        gross_r = (
            (execution_exit - entry_price) / r_denominator
            if side == "LONG"
            else (entry_price - execution_exit) / r_denominator
        )
        fee_r = (
            entry_price * entry_fee_rate + execution_exit * exit_fee_rate
        ) / r_denominator
        net_r = gross_r - fee_r
        result = "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN")
        return {
            "result": result,
            "net_r": float(net_r),
            "gross_r": float(gross_r),
            "fee_r": float(fee_r),
            "side": side,
            "entry_price": float(entry_price),
            "stop_price": float(stop_price),
            "target_price": float(target_price),
            "exit_time": _utc(row["period_start"], "intrabar exit_time").isoformat(),
            "raw_exit_price": float(raw_exit),
            "exit_price": float(execution_exit),
            "exit_reason": "TP" if use_tp else "SL",
            "ambiguous_same_1m_bar": ambiguous,
            "tie_policy": tie,
            "account_r_distance": float(r_denominator),
        }
    return None


def replay_opposite_one_r(
    control: Any,
    reports: Any,
    *,
    reference_run: str,
    teacher: dict[str, Any],
    entry_context: dict[str, Any],
    opposite_side: str,
) -> dict[str, Any]:
    """Replay an opposite 1R outcome without reading beyond the teacher boundary."""
    try:
        manifest = reports.get_run_manifest(reference_run)
        run_dir = reports.resolve_run(reference_run)
        profile = str(teacher.get("strategy_profile_key") or "").lower()
        execution, profile_cfg = _validate_simple_one_r(manifest, profile)
        trade_context = dict((entry_context or {}).get("trade_entry_context") or {})
        context = _teacher_trade_context(manifest, run_dir, teacher, trade_context)

        source_side = str(context.get("side") or teacher.get("side") or "").upper()
        if source_side not in {"LONG", "SHORT"}:
            raise ValueError("immutable teacher trade has no valid source side")
        opposite = str(opposite_side).upper()
        if opposite == source_side or opposite not in {"LONG", "SHORT"}:
            raise ValueError("opposite replay side is not the inverse teacher direction")

        entry_time = _utc(
            context.get("entry_time") or teacher.get("entry_time"), "teacher entry_time"
        )
        boundary = _utc(teacher.get("resolution_time"), "teacher resolution_time")
        if boundary < entry_time:
            raise ValueError("teacher resolution precedes entry")
        if entry_time.floor("1min") != entry_time:
            raise ValueError("teacher entry timestamp is not aligned to immutable 1m candles")

        source_entry = float(context.get("entry_price"))
        atr = float(context.get("atr_at_entry"))
        if not pd.notna(source_entry) or source_entry <= 0:
            raise ValueError("immutable teacher trade has no valid entry_price")
        if not pd.notna(atr) or atr <= 0:
            raise ValueError("immutable teacher trade has no valid atr_at_entry")

        slippage = float(execution.get("slippage", 0.0) or 0.0)
        if source_side == "LONG":
            raw_entry = source_entry / (1.0 + slippage)
        else:
            if slippage >= 1.0:
                raise ValueError("invalid immutable slippage")
            raw_entry = source_entry / (1.0 - slippage)
        opposite_entry = raw_entry * (
            1.0 + slippage if opposite == "LONG" else 1.0 - slippage
        )

        atr_multiplier = float(execution.get("atr_multiplier", 1.0) or 1.0)
        stop_multiple = float(profile_cfg.get("stop_loss_multiple", 1.0) or 1.0)
        stop_distance = atr * atr_multiplier * stop_multiple
        if stop_distance <= 0:
            raise ValueError("immutable ATR stop distance is not positive")
        sizing_override = bool(
            profile_cfg.get("position_sizing_stop_override_enabled", False)
        )
        sizing_stop_multiple = float(
            profile_cfg.get("position_sizing_stop_multiple", stop_multiple)
            or stop_multiple
        )
        account_r_distance = (
            atr * atr_multiplier * sizing_stop_multiple
            if sizing_override
            else stop_distance
        )
        if account_r_distance <= 0:
            raise ValueError("immutable position-sizing stop distance is not positive")

        frame, provenance = _verified_intrabar_frame(
            control,
            manifest,
            run_dir,
            start=entry_time,
            end_inclusive=boundary,
        )
        entry_fee_rate = float(
            execution.get("maker_fee" if execution.get("use_maker_entry") else "taker_fee", 0.0)
            or 0.0
        )
        exit_fee_rate = float(
            execution.get("maker_fee" if execution.get("use_maker_exit") else "taker_fee", 0.0)
            or 0.0
        )
        outcome = _simulate_simple_one_r(
            frame,
            side=opposite,
            entry_price=opposite_entry,
            stop_distance=stop_distance,
            account_r_distance=account_r_distance,
            slippage=slippage,
            tie_policy=str(execution.get("tie_policy", "PESSIMISTIC")),
            entry_fee_rate=entry_fee_rate,
            exit_fee_rate=exit_fee_rate,
        )
        if outcome is None:
            return {
                "available": False,
                "side": opposite,
                "source": REPLAY_SOURCE,
                "reason": (
                    "opposite 1R hypothetical was not resolved by the teacher-loss causal boundary; "
                    "later intrabar data was not inspected"
                ),
                "causal_cutoff": boundary.isoformat(),
                "bars_scanned": int(len(frame)),
                **provenance,
            }

        outcome.update(
            {
                "source": REPLAY_SOURCE,
                "causally_resolved_by_teacher_boundary": True,
                "teacher_resolution_time": boundary.isoformat(),
                "atr_at_entry": float(atr),
                "atr_multiplier": float(atr_multiplier),
                "stop_loss_multiple": float(stop_multiple),
                "position_sizing_stop_override_enabled": sizing_override,
                "position_sizing_stop_multiple": float(sizing_stop_multiple),
                "position_sizing_reference_distance": float(account_r_distance),
                "reward_risk_ratio": 1.0,
                "source_teacher_side": source_side,
                "source_teacher_entry_price": float(source_entry),
                "raw_entry_price": float(raw_entry),
                **provenance,
            }
        )
        return {
            "available": True,
            "side": opposite,
            "source": REPLAY_SOURCE,
            "outcome": outcome,
        }
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return {
            "available": False,
            "side": str(opposite_side).upper(),
            "source": REPLAY_SOURCE,
            "reason": str(exc),
        }
