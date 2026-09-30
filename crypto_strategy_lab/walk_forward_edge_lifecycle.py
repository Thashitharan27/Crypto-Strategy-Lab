"""Single-strategy causal edge lifecycle replay for walk-forward experiments.

This module is intentionally read-only. It replays the authoritative resolved
RESEARCH trades in causal order and applies an opt-in LIVE/SHADOW capital gate.
The underlying walk-forward chronology, rule learning, candidate generation and
RESEARCH equity are never changed.

A transition is effective only after the resolved trade that supplied the
evidence. Therefore a losing LIVE trade that triggers suspension remains a LIVE
trade, and a winning SHADOW trade that confirms recovery remains a SHADOW trade.
Only the next causally later trade sees the new capital state.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from crypto_strategy_lab.causal_experiment import CausalExperimentStore


EDGE_LIFECYCLE_CONTRACT = "causal_single_strategy_edge_lifecycle_v1"
_VALID_STATES = {"LIVE", "SHADOW"}


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer >= {minimum}") from exc
    if parsed < minimum or parsed != float(value):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return parsed


def normalize_edge_lifecycle_policy(raw: Any) -> dict[str, Any] | None:
    """Validate the immutable per-experiment edge lifecycle policy.

    No numeric edge thresholds are invented. When enabled, callers must freeze
    every threshold in the experiment definition so the historical replay cannot
    be tuned after outcomes are known.
    """
    if raw in (None, False):
        return None
    if not isinstance(raw, dict):
        raise ValueError("edge_lifecycle_policy must be an object")
    enabled = raw.get("enabled", False)
    if enabled is not True:
        return None

    required = {
        "live_lookback_trades",
        "live_min_trades",
        "suspend_expectancy_r",
        "suspend_net_r",
        "shadow_lookback_trades",
        "shadow_min_trades",
        "recover_expectancy_r",
        "recover_net_r",
    }
    missing = sorted(key for key in required if key not in raw)
    if missing:
        raise ValueError(
            "enabled edge_lifecycle_policy is missing required fields: "
            + ", ".join(missing)
        )

    live_lookback = _positive_int(raw["live_lookback_trades"], "live_lookback_trades", minimum=2)
    live_min = _positive_int(raw["live_min_trades"], "live_min_trades", minimum=live_lookback)
    shadow_lookback = _positive_int(raw["shadow_lookback_trades"], "shadow_lookback_trades", minimum=2)
    shadow_min = _positive_int(raw["shadow_min_trades"], "shadow_min_trades", minimum=shadow_lookback)
    suspend_expectancy = _number(raw["suspend_expectancy_r"], "suspend_expectancy_r")
    suspend_net = _number(raw["suspend_net_r"], "suspend_net_r")
    recover_expectancy = _number(raw["recover_expectancy_r"], "recover_expectancy_r")
    recover_net = _number(raw["recover_net_r"], "recover_net_r")
    if recover_expectancy <= suspend_expectancy:
        raise ValueError(
            "recover_expectancy_r must be greater than suspend_expectancy_r "
            "to provide LIVE/SHADOW hysteresis"
        )
    if recover_net <= suspend_net:
        raise ValueError(
            "recover_net_r must be greater than suspend_net_r "
            "to provide LIVE/SHADOW hysteresis"
        )

    initial_state = str(raw.get("initial_state", "LIVE")).strip().upper()
    if initial_state not in _VALID_STATES:
        raise ValueError("edge_lifecycle_policy.initial_state must be LIVE or SHADOW")

    return {
        "enabled": True,
        "initial_state": initial_state,
        "live_lookback_trades": live_lookback,
        "live_min_trades": live_min,
        "suspend_expectancy_r": suspend_expectancy,
        "suspend_net_r": suspend_net,
        "shadow_lookback_trades": shadow_lookback,
        "shadow_min_trades": shadow_min,
        "recover_expectancy_r": recover_expectancy,
        "recover_net_r": recover_net,
    }


def _resolved_research_trades(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "TRADE_RESOLVED":
            continue
        payload = event.get("payload") or {}
        if str(payload.get("ledger", "RESEARCH")).strip().upper() != "RESEARCH":
            continue
        candidate_id = str(payload.get("candidate_id", "")).strip()
        if not candidate_id:
            continue
        raw_net_r = payload.get("net_r")
        if raw_net_r is None:
            continue
        net_r = float(raw_net_r)
        rows.append(
            {
                "candidate_id": candidate_id,
                "sequence": int(event["sequence"]),
                "resolved_time": (
                    event.get("effective_market_time")
                    or event.get("event_time")
                    or event.get("recorded_at")
                ),
                "net_r": net_r,
                "result": str(
                    payload.get("result")
                    or ("WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN"))
                ).upper(),
            }
        )
    rows.sort(key=lambda row: row["sequence"])
    return rows


def _perf(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in rows]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    total = len(values)
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "breakevens": total - wins - losses,
        "win_rate_pct": round(100.0 * wins / total, 2) if total else None,
        "net_r": round(sum(values), 10),
        "expectancy_r": round(sum(values) / total, 10) if total else None,
        "profit_factor": round(gross_profit / gross_loss, 10) if gross_loss > 0 else None,
    }


def _window_stats(rows: list[dict[str, Any]], lookback: int) -> dict[str, Any]:
    selected = rows[-lookback:]
    stats = _perf(selected)
    stats["lookback_trades"] = lookback
    stats["window_trade_count"] = len(selected)
    return stats


def _risk_model(definition: dict[str, Any]) -> tuple[float, float]:
    risk = definition.get("risk_model") or {}
    initial = risk.get("initial_equity", definition.get("initial_equity", 1000.0))
    initial_equity = float(initial)
    if initial_equity <= 0:
        raise ValueError("walk-forward initial equity must be positive")

    if risk.get("risk_per_trade") is not None:
        risk_fraction = float(risk["risk_per_trade"])
    elif definition.get("risk_pct") is not None:
        risk_fraction = float(definition["risk_pct"]) / 100.0
    else:
        risk_fraction = 0.01
    if not 0 < risk_fraction <= 1:
        raise ValueError("walk-forward risk_per_trade must be in (0, 1]")
    return initial_equity, risk_fraction


def _equity(initial_equity: float, risk_fraction: float, rows: Iterable[dict[str, Any]]) -> float:
    equity = float(initial_equity)
    for row in rows:
        equity += equity * risk_fraction * float(row["net_r"])
    return round(equity, 10)


def summarize_walk_forward_edge_lifecycle(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
) -> dict[str, Any]:
    """Replay one experiment immutable strategy-level LIVE/SHADOW policy."""
    del reports
    store = CausalExperimentStore(Path(control.project_root) / "walk_forward_experiments")
    readback = store.read_fast(experiment_id, recent_events=0)
    definition = ((readback.get("manifest") or {}).get("definition") or {})
    policy = normalize_edge_lifecycle_policy(definition.get("edge_lifecycle_policy"))
    if policy is None:
        return {
            "contract": EDGE_LIFECYCLE_CONTRACT,
            "read_only": True,
            "experiment_id": experiment_id,
            "sequence": int(readback["sequence"]),
            "state_hash": str(readback["state_hash"]),
            "enabled": False,
            "reason": (
                "No enabled edge_lifecycle_policy is frozen in this experiment definition. "
                "Thresholds are intentionally not invented after outcomes are known."
            ),
        }

    events = store.indexed_events(experiment_id, event_types={"TRADE_RESOLVED"})
    confirmed = store.read_fast(experiment_id, recent_events=0)
    if (
        int(confirmed["sequence"]) != int(readback["sequence"])
        or str(confirmed["state_hash"]) != str(readback["state_hash"])
    ):
        raise ValueError("walk-forward event chain changed during edge lifecycle replay")

    trades = _resolved_research_trades(events)
    state = policy["initial_state"]
    live_rows: list[dict[str, Any]] = []
    shadow_rows: list[dict[str, Any]] = []
    live_since_transition: list[dict[str, Any]] = []
    shadow_since_transition: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    annotated: list[dict[str, Any]] = []

    for row in trades:
        state_before = state
        enriched = dict(row)
        enriched["capital_state"] = state_before

        if state_before == "LIVE":
            live_rows.append(enriched)
            live_since_transition.append(enriched)
            shadow_since_transition.clear()
            if len(live_since_transition) >= policy["live_min_trades"]:
                stats = _window_stats(live_since_transition, policy["live_lookback_trades"])
                if (
                    float(stats["expectancy_r"]) <= policy["suspend_expectancy_r"]
                    and float(stats["net_r"]) <= policy["suspend_net_r"]
                ):
                    state = "SHADOW"
                    transitions.append(
                        {
                            "from": "LIVE",
                            "to": "SHADOW",
                            "effective_after_sequence": row["sequence"],
                            "effective_after_candidate_id": row["candidate_id"],
                            "effective_after_time": row["resolved_time"],
                            "reason": "EDGE_DECAY_CONFIRMED",
                            "evidence": stats,
                        }
                    )
                    shadow_since_transition.clear()
        else:
            shadow_rows.append(enriched)
            shadow_since_transition.append(enriched)
            live_since_transition.clear()
            if len(shadow_since_transition) >= policy["shadow_min_trades"]:
                stats = _window_stats(shadow_since_transition, policy["shadow_lookback_trades"])
                if (
                    float(stats["expectancy_r"]) >= policy["recover_expectancy_r"]
                    and float(stats["net_r"]) >= policy["recover_net_r"]
                ):
                    state = "LIVE"
                    transitions.append(
                        {
                            "from": "SHADOW",
                            "to": "LIVE",
                            "effective_after_sequence": row["sequence"],
                            "effective_after_candidate_id": row["candidate_id"],
                            "effective_after_time": row["resolved_time"],
                            "reason": "EDGE_RECOVERY_CONFIRMED",
                            "evidence": stats,
                        }
                    )
                    live_since_transition.clear()

        enriched["state_after_resolution"] = state
        annotated.append(enriched)

    initial_equity, risk_fraction = _risk_model(definition)
    continuous = _perf(trades)
    managed = _perf(live_rows)
    shadow = _perf(shadow_rows)
    shadow_values = [float(row["net_r"]) for row in shadow_rows]
    losses_avoided_r = -sum(value for value in shadow_values if value < 0)
    profits_missed_r = sum(value for value in shadow_values if value > 0)

    return {
        "contract": EDGE_LIFECYCLE_CONTRACT,
        "read_only": True,
        "experiment_id": experiment_id,
        "strategy": definition.get("strategy"),
        "symbol": definition.get("symbol"),
        "strategy_timeframe": definition.get("strategy_timeframe"),
        "sequence": int(readback["sequence"]),
        "state_hash": str(readback["state_hash"]),
        "enabled": True,
        "policy": policy,
        "current_capital_state": state,
        "transitions": transitions,
        "transition_count": len(transitions),
        "performance": {
            "continuous_strategy": {
                **continuous,
                "final_equity": _equity(initial_equity, risk_fraction, trades),
            },
            "edge_managed_live": {
                **managed,
                "final_equity": _equity(initial_equity, risk_fraction, live_rows),
            },
            "shadow_only": shadow,
            "capital_gate_effect": {
                "losses_avoided_r": round(losses_avoided_r, 10),
                "profits_missed_r": round(profits_missed_r, 10),
                "shadow_net_r": round(sum(shadow_values), 10),
                "managed_minus_continuous_net_r": round(-sum(shadow_values), 10),
            },
        },
        "trade_states": annotated,
        "methodology": {
            "unit": "single strategy",
            "state_change_timing": "after_resolved_trade",
            "shadow_observation_continues": True,
            "changes_original_walk_forward": False,
            "note": (
                "The original RESEARCH ledger remains authoritative. This read-only replay asks "
                "whether a policy frozen in the experiment definition would have gated capital "
                "while continuing to observe every strategy trade in SHADOW."
            ),
        },
    }
