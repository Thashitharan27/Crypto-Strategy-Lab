"""Immutable 1m replay for prospective walk-forward trades created by active FLIP rules.

This is intentionally narrower than normal EVE outcome lookup. It is used only
when a previously learned causal FLIP changes the executable strategy side and
the immutable reference run has no unique EVE row for that opposite side.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from crypto_strategy_lab.walk_forward_opposite_replay import (
    REPLAY_SOURCE,
    _simulate_simple_one_r,
    _utc,
    _validate_simple_one_r,
    _verified_intrabar_frame,
)


def replay_flipped_candidate_one_r(
    control: Any,
    reports: Any,
    *,
    reference_run: str,
    candidate: dict[str, Any],
    strategy_action: str,
) -> dict[str, Any]:
    """Return the deterministic flipped-side outcome from immutable 1m candles.

    The caller must already have durably frozen the ChatGPT view. This function
    never changes the candidate or decision event; it only reconstructs the
    already-active FLIP's executable 1R trade when an opposite EVE row is absent.
    """
    manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)

    source_side = str(candidate.get("source_side") or "").strip().upper()
    flipped_side = str(strategy_action or "").strip().upper()
    if source_side not in {"LONG", "SHORT"} or flipped_side not in {"LONG", "SHORT"}:
        raise ValueError("prospective FLIP replay requires valid source and executable sides")
    if flipped_side == source_side:
        raise ValueError("prospective FLIP replay is only valid when execution side was flipped")
    if flipped_side != ("SHORT" if source_side == "LONG" else "LONG"):
        raise ValueError("prospective FLIP replay side is not the inverse source direction")
    if not list(candidate.get("matched_flip_groups") or []):
        raise ValueError("prospective FLIP replay requires an already-active matched FLIP rule")

    profile = str(candidate.get("strategy_profile_key") or "").strip().lower()
    if not profile:
        raise ValueError("captured candidate has no strategy profile for FLIP replay")
    execution, profile_cfg = _validate_simple_one_r(manifest, profile)

    atr_multiplier = float(execution.get("atr_multiplier", 1.0) or 1.0)
    stop_multiple = float(profile_cfg.get("stop_loss_multiple", 1.0) or 1.0)
    if abs((atr_multiplier * stop_multiple) - 1.0) > 1e-12:
        raise ValueError("prospective FLIP replay is limited to an exact 1 ATR stop")
    tie_policy = str(execution.get("tie_policy", "PESSIMISTIC")).strip().upper()
    if tie_policy != "PESSIMISTIC":
        raise ValueError("prospective FLIP replay requires pessimistic same-bar tie handling")

    trade_context = dict(((candidate.get("context") or {}).get("trade_entry_context") or {}))
    entry_time = _utc(
        trade_context.get("entry_time") or candidate.get("entry_time"),
        "candidate entry_time",
    )
    if entry_time.floor("1min") != entry_time:
        raise ValueError("candidate entry timestamp is not aligned to immutable 1m candles")

    try:
        source_entry = float(trade_context.get("entry_price"))
        atr = float(trade_context.get("atr_at_entry"))
    except (TypeError, ValueError) as exc:
        raise ValueError("captured candidate lacks numeric entry_price/atr_at_entry") from exc
    if not pd.notna(source_entry) or source_entry <= 0:
        raise ValueError("captured candidate has no valid source entry_price")
    if not pd.notna(atr) or atr <= 0:
        raise ValueError("captured candidate has no valid atr_at_entry")

    slippage = float(execution.get("slippage", 0.0) or 0.0)
    if slippage < 0 or slippage >= 1:
        raise ValueError("immutable execution slippage is invalid")
    raw_entry = (
        source_entry / (1.0 + slippage)
        if source_side == "LONG"
        else source_entry / (1.0 - slippage)
    )
    replay_entry = raw_entry * (
        1.0 + slippage if flipped_side == "LONG" else 1.0 - slippage
    )
    stop_distance = atr * atr_multiplier * stop_multiple

    request = manifest.get("request") or {}
    run_end_raw = request.get("end")
    if run_end_raw in (None, ""):
        raise ValueError("immutable reference manifest has no run end for prospective replay")
    end_inclusive = _utc(run_end_raw, "reference run end") - pd.Timedelta(minutes=1)
    if end_inclusive < entry_time:
        raise ValueError("candidate entry lies beyond immutable reference-run coverage")

    frame, provenance = _verified_intrabar_frame(
        control,
        manifest,
        run_dir,
        start=entry_time,
        end_inclusive=end_inclusive,
    )
    entry_fee_rate = float(
        execution.get(
            "maker_fee" if execution.get("use_maker_entry") else "taker_fee",
            0.0,
        )
        or 0.0
    )
    exit_fee_rate = float(
        execution.get(
            "maker_fee" if execution.get("use_maker_exit") else "taker_fee",
            0.0,
        )
        or 0.0
    )
    outcome = _simulate_simple_one_r(
        frame,
        side=flipped_side,
        entry_price=replay_entry,
        stop_distance=stop_distance,
        slippage=slippage,
        tie_policy=tie_policy,
        entry_fee_rate=entry_fee_rate,
        exit_fee_rate=exit_fee_rate,
    )
    if outcome is None:
        raise ValueError(
            "flipped 1R trade did not resolve within immutable reference-run 1m coverage; "
            "decision remains frozen and equity is unchanged"
        )

    outcome.update(
        {
            "source": REPLAY_SOURCE,
            "replay_reason": "ACTIVE_CAUSAL_FLIP_WITHOUT_UNIQUE_OPPOSITE_EVE",
            "reference_source_sample_id": candidate.get("reference_sample_id"),
            "research_signal_index": candidate.get("research_signal_index"),
            "source_side": source_side,
            "strategy_action": flipped_side,
            "source_entry_price": float(source_entry),
            "raw_entry_price": float(raw_entry),
            "atr_at_entry": float(atr),
            "atr_multiplier": float(atr_multiplier),
            "stop_loss_multiple": float(stop_multiple),
            "reward_risk_ratio": 1.0,
            "reference_run_end": _utc(run_end_raw, "reference run end").isoformat(),
            **provenance,
        }
    )
    return outcome
