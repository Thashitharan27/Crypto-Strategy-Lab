"""Causal empirical-Bayes probability research for completed strategy trades.

The scorer is deliberately downstream of the simulator.  It never changes a fill,
entry, exit or direction.  Each entry is scored using only outcomes that were
already completed by that entry timestamp, so future trades cannot leak into the
probability estimate.

The model is intentionally small and auditable rather than a black-box classifier:

* a Beta-Bernoulli side prior estimates the historical probability of a profitable
  LONG or SHORT;
* a coarse market-context posterior is shrunk toward that side prior so tiny
  samples cannot produce extreme probabilities;
* expected net R is shrunk in the same way;
* LONG and SHORT are scored independently from historically observed trades on
  those sides.  The opposite-side score is therefore research evidence, not a
  counterfactual claim about a trade that was never executed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import heapq
import math
from typing import Iterable

import numpy as np
import pandas as pd


MODEL_VERSION = "BETA_CONTEXT_V1"
DEFAULT_PRIOR_STRENGTH = 20.0
DEFAULT_MIN_CONTEXT_SAMPLES = 20
DEFAULT_THRESHOLDS = (0.55, 0.60, 0.65, 0.70)


@dataclass
class _Stats:
    wins: int = 0
    losses: int = 0
    net_r_sum: float = 0.0

    @property
    def samples(self) -> int:
        return self.wins + self.losses

    def add(self, won: bool, net_r: float) -> None:
        if won:
            self.wins += 1
        else:
            self.losses += 1
        if np.isfinite(net_r):
            self.net_r_sum += float(net_r)


@dataclass(frozen=True)
class BayesianEstimate:
    side: str
    probability: float
    prior_probability: float
    expected_net_r: float
    context_samples: int
    side_samples: int
    lower_90: float
    upper_90: float
    confidence: str


def _numeric(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if np.isfinite(result) else math.nan


def _bucket(value, edges: tuple[float, ...]) -> str:
    value = _numeric(value)
    if not np.isfinite(value):
        return "UNKNOWN"
    lower = None
    for edge in edges:
        if value < edge:
            return f"<{edge:g}" if lower is None else f"{lower:g}-{edge:g}"
        lower = edge
    return f"{edges[-1]:g}+"


def _pressure_state(row: pd.Series, side: str) -> str:
    plus_change = _numeric(row.get("plus_di_change"))
    minus_change = _numeric(row.get("minus_di_change"))
    if not np.isfinite(plus_change) or not np.isfinite(minus_change):
        return "UNKNOWN"
    directional, opposing = (
        (plus_change, minus_change) if side == "LONG" else (minus_change, plus_change)
    )
    if directional > 0 and opposing < 0:
        return "EXPANDING"
    if directional < 0 and opposing > 0:
        return "CONTRACTING"
    return "MIXED"


def _context_key(row: pd.Series, side: str) -> tuple[str, str, str, str, str]:
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"unsupported Bayesian side: {side}")

    regime_raw = row.get("market_regime")
    regime = "UNKNOWN" if pd.isna(regime_raw) else str(regime_raw).upper()
    plus_di = _numeric(row.get("plus_di"))
    minus_di = _numeric(row.get("minus_di"))
    if not np.isfinite(plus_di) or not np.isfinite(minus_di):
        di_relation = "UNKNOWN"
    elif plus_di == minus_di:
        di_relation = "TIE"
    else:
        dominant = "LONG" if plus_di > minus_di else "SHORT"
        di_relation = "AGREE" if dominant == side else "COUNTER"

    directional_di = plus_di if side == "LONG" else minus_di
    return (
        regime,
        di_relation,
        _bucket(directional_di, (10.0, 20.0, 30.0, 40.0)),
        _bucket(row.get("adx"), (15.0, 20.0, 25.0, 30.0, 40.0)),
        _pressure_state(row, side),
    )


def _confidence(context_samples: int) -> str:
    if context_samples >= 60:
        return "HIGH"
    if context_samples >= DEFAULT_MIN_CONTEXT_SAMPLES:
        return "MEDIUM"
    return "LOW"


class BayesianTradeModel:
    """Small causal empirical-Bayes model updated only with known trade outcomes."""

    def __init__(self, prior_strength: float = DEFAULT_PRIOR_STRENGTH) -> None:
        if prior_strength <= 0:
            raise ValueError("Bayesian prior strength must be positive")
        self.prior_strength = float(prior_strength)
        self.side_stats = {"LONG": _Stats(), "SHORT": _Stats()}
        self.context_stats: dict[tuple[str, tuple[str, ...]], _Stats] = defaultdict(_Stats)

    def observe(self, row: pd.Series) -> None:
        side = str(row.get("side", "")).upper()
        if side not in self.side_stats:
            return
        pnl = _numeric(row.get("pair_net_pnl"))
        if not np.isfinite(pnl):
            return
        net_r = _numeric(row.get("pair_net_r"))
        won = pnl > 0
        key = _context_key(row, side)
        self.side_stats[side].add(won, net_r)
        self.context_stats[(side, key)].add(won, net_r)

    def estimate(self, row: pd.Series, side: str) -> BayesianEstimate:
        side = str(side).upper()
        if side not in self.side_stats:
            raise ValueError(f"unsupported Bayesian side: {side}")

        baseline = self.side_stats[side]
        # Beta(1,1) keeps an unseen side neutral at 50% and prevents 0/100% priors.
        prior_probability = (baseline.wins + 1.0) / (baseline.samples + 2.0)
        prior_expected_r = (
            baseline.net_r_sum / baseline.samples if baseline.samples else 0.0
        )

        context = self.context_stats[(side, _context_key(row, side))]
        alpha = prior_probability * self.prior_strength + context.wins
        beta = (1.0 - prior_probability) * self.prior_strength + context.losses
        total = alpha + beta
        probability = alpha / total

        # Normal approximation to a Beta posterior is sufficient for this
        # diagnostic interval and avoids adding a scipy dependency.
        variance = (alpha * beta) / (total * total * (total + 1.0))
        radius = 1.645 * math.sqrt(max(0.0, variance))
        lower = max(0.0, probability - radius)
        upper = min(1.0, probability + radius)
        expected_r = (
            prior_expected_r * self.prior_strength + context.net_r_sum
        ) / (self.prior_strength + context.samples)

        return BayesianEstimate(
            side=side,
            probability=float(probability),
            prior_probability=float(prior_probability),
            expected_net_r=float(expected_r),
            context_samples=int(context.samples),
            side_samples=int(baseline.samples),
            lower_90=float(lower),
            upper_90=float(upper),
            confidence=_confidence(context.samples),
        )


def _entry_column(trades: pd.DataFrame) -> str:
    for name in ("actual_entry_timestamp", "entry_time", "strategy_entry_time"):
        if name in trades.columns:
            return name
    raise ValueError("Bayesian research requires an entry timestamp column")


def _required_columns(trades: pd.DataFrame) -> None:
    required = {"side", "exit_time", "pair_net_pnl", "pair_net_r"}
    missing = sorted(required - set(trades.columns))
    if missing:
        raise ValueError(f"Bayesian research missing trade columns: {missing}")
    _entry_column(trades)


def _threshold_column(threshold: float, min_context_samples: int) -> str:
    pct = int(round(float(threshold) * 100))
    return f"bayes_take_{pct}_min{int(min_context_samples)}"


def enrich_bayesian_trade_probabilities(
    trades: pd.DataFrame,
    *,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    min_context_samples: int = DEFAULT_MIN_CONTEXT_SAMPLES,
    thresholds: Iterable[float] = DEFAULT_THRESHOLDS,
) -> pd.DataFrame:
    """Attach causal walk-forward LONG/SHORT probabilities to ``trades`` in place.

    A historical result becomes learnable only after its exit timestamp.  This
    mirrors the event order of the simulator: a trade that is still open at an
    entry decision cannot teach that decision its eventual outcome.
    """
    if min_context_samples < 1:
        raise ValueError("Bayesian minimum context samples must be positive")
    thresholds = tuple(float(value) for value in thresholds)
    if any(not 0.0 < value < 1.0 for value in thresholds):
        raise ValueError("Bayesian thresholds must be between 0 and 1")

    base_columns = {
        "bayes_model_version": pd.Series(dtype="string"),
        "bayes_long_probability": pd.Series(dtype="float64"),
        "bayes_short_probability": pd.Series(dtype="float64"),
        "bayes_actual_side_probability": pd.Series(dtype="float64"),
        "bayes_actual_side_prior_probability": pd.Series(dtype="float64"),
        "bayes_probability_edge_long_minus_short": pd.Series(dtype="float64"),
        "bayes_expected_net_r_long": pd.Series(dtype="float64"),
        "bayes_expected_net_r_short": pd.Series(dtype="float64"),
        "bayes_long_context_samples": pd.Series(dtype="int64"),
        "bayes_short_context_samples": pd.Series(dtype="int64"),
        "bayes_long_side_samples": pd.Series(dtype="int64"),
        "bayes_short_side_samples": pd.Series(dtype="int64"),
        "bayes_actual_context_samples": pd.Series(dtype="int64"),
        "bayes_actual_side_confidence": pd.Series(dtype="string"),
        "bayes_long_lower_90": pd.Series(dtype="float64"),
        "bayes_long_upper_90": pd.Series(dtype="float64"),
        "bayes_short_lower_90": pd.Series(dtype="float64"),
        "bayes_short_upper_90": pd.Series(dtype="float64"),
        "bayes_context_ready": pd.Series(dtype="bool"),
        "bayes_recommended_direction": pd.Series(dtype="string"),
        "bayes_recommendation_matches_actual": pd.Series(dtype="bool"),
    }
    threshold_columns = {
        _threshold_column(value, min_context_samples): pd.Series(dtype="bool")
        for value in thresholds
    }
    if trades.empty:
        for name, values in {**base_columns, **threshold_columns}.items():
            trades[name] = values
        trades.attrs["bayesian_threshold_simulation"] = []
        return trades

    _required_columns(trades)
    entry_name = _entry_column(trades)
    entries = pd.to_datetime(trades[entry_name], utc=True, errors="coerce")
    exits = pd.to_datetime(trades["exit_time"], utc=True, errors="coerce")
    if entries.isna().any():
        raise ValueError("Bayesian research found a trade with an invalid entry timestamp")
    if exits.isna().any():
        raise ValueError("Bayesian research found a trade with an invalid exit timestamp")
    if (exits < entries).any():
        raise ValueError("Bayesian research found an exit timestamp before entry")

    model = BayesianTradeModel(prior_strength=prior_strength)
    # Heap payloads are minimal immutable observations; no full DataFrame or attrs
    # are copied.  This matters for runs containing many rejected-signal records.
    pending: list[tuple[int, int, pd.Series]] = []
    order = np.argsort(entries.astype("int64").to_numpy(), kind="stable")
    scored: dict[int, dict[str, object]] = {}

    for sequence, position in enumerate(order):
        entry_ns = int(entries.iloc[position].value)
        while pending and pending[0][0] <= entry_ns:
            _exit_ns, _serial, completed = heapq.heappop(pending)
            model.observe(completed)

        row = trades.iloc[position]
        long_estimate = model.estimate(row, "LONG")
        short_estimate = model.estimate(row, "SHORT")
        actual_side = str(row.get("side", "")).upper()
        actual = long_estimate if actual_side == "LONG" else short_estimate
        ready = actual.context_samples >= min_context_samples

        if (
            long_estimate.context_samples >= min_context_samples
            and short_estimate.context_samples >= min_context_samples
            and abs(long_estimate.probability - short_estimate.probability) >= 0.05
            and max(long_estimate.probability, short_estimate.probability) >= 0.55
        ):
            recommendation = (
                "LONG"
                if long_estimate.probability > short_estimate.probability
                else "SHORT"
            )
        else:
            recommendation = "ABSTAIN"

        result: dict[str, object] = {
            "bayes_model_version": MODEL_VERSION,
            "bayes_long_probability": long_estimate.probability,
            "bayes_short_probability": short_estimate.probability,
            "bayes_actual_side_probability": actual.probability,
            "bayes_actual_side_prior_probability": actual.prior_probability,
            "bayes_probability_edge_long_minus_short": (
                long_estimate.probability - short_estimate.probability
            ),
            "bayes_expected_net_r_long": long_estimate.expected_net_r,
            "bayes_expected_net_r_short": short_estimate.expected_net_r,
            "bayes_long_context_samples": long_estimate.context_samples,
            "bayes_short_context_samples": short_estimate.context_samples,
            "bayes_long_side_samples": long_estimate.side_samples,
            "bayes_short_side_samples": short_estimate.side_samples,
            "bayes_actual_context_samples": actual.context_samples,
            "bayes_actual_side_confidence": actual.confidence,
            "bayes_long_lower_90": long_estimate.lower_90,
            "bayes_long_upper_90": long_estimate.upper_90,
            "bayes_short_lower_90": short_estimate.lower_90,
            "bayes_short_upper_90": short_estimate.upper_90,
            "bayes_context_ready": bool(ready),
            "bayes_recommended_direction": recommendation,
            "bayes_recommendation_matches_actual": (
                recommendation == actual_side if recommendation != "ABSTAIN" else False
            ),
        }
        for threshold in thresholds:
            result[_threshold_column(threshold, min_context_samples)] = bool(
                ready and actual.probability >= threshold
            )
        scored[int(position)] = result

        # Store only the fields needed by a later causal update.
        completed = pd.Series(
            {
                "side": actual_side,
                "pair_net_pnl": row.get("pair_net_pnl"),
                "pair_net_r": row.get("pair_net_r"),
                "market_regime": row.get("market_regime"),
                "plus_di": row.get("plus_di"),
                "minus_di": row.get("minus_di"),
                "plus_di_change": row.get("plus_di_change"),
                "minus_di_change": row.get("minus_di_change"),
                "adx": row.get("adx"),
            }
        )
        heapq.heappush(
            pending,
            (int(exits.iloc[position].value), sequence, completed),
        )

    names = list(next(iter(scored.values())))
    for name in names:
        trades[name] = [scored[position][name] for position in range(len(trades))]

    simulation = threshold_simulation(
        trades,
        thresholds=thresholds,
        min_context_samples=min_context_samples,
    )
    trades.attrs["bayesian_threshold_simulation"] = simulation.to_dict("records")
    return trades


def threshold_simulation(
    scored_trades: pd.DataFrame,
    *,
    thresholds: Iterable[float] = DEFAULT_THRESHOLDS,
    min_context_samples: int = DEFAULT_MIN_CONTEXT_SAMPLES,
) -> pd.DataFrame:
    """Summarize take/skip results for causal posterior-probability thresholds."""
    thresholds = tuple(float(value) for value in thresholds)
    rows: list[dict[str, object]] = []
    total = len(scored_trades)
    for threshold in thresholds:
        name = _threshold_column(threshold, min_context_samples)
        if name not in scored_trades.columns:
            mask = (
                pd.to_numeric(
                    scored_trades.get(
                        "bayes_actual_side_probability",
                        pd.Series(index=scored_trades.index, dtype=float),
                    ),
                    errors="coerce",
                )
                >= threshold
            ) & (
                pd.to_numeric(
                    scored_trades.get(
                        "bayes_actual_context_samples",
                        pd.Series(index=scored_trades.index, dtype=float),
                    ),
                    errors="coerce",
                )
                >= min_context_samples
            )
        else:
            mask = scored_trades[name].fillna(False).astype(bool)
        selected = scored_trades.loc[mask]
        pnl = pd.to_numeric(selected.get("pair_net_pnl", pd.Series(dtype=float)), errors="coerce")
        net_r = pd.to_numeric(selected.get("pair_net_r", pd.Series(dtype=float)), errors="coerce")
        rows.append(
            {
                "minimum_probability": threshold,
                "minimum_context_samples": int(min_context_samples),
                "trades": int(len(selected)),
                "retained_percentage": float(len(selected) / total) if total else 0.0,
                "wins": int((pnl > 0).sum()),
                "losses": int((pnl < 0).sum()),
                "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
                "total_net_r": float(net_r.sum()) if len(net_r) else 0.0,
                "average_net_r": float(net_r.mean()) if len(net_r) else 0.0,
                "net_pnl": float(pnl.sum()) if len(pnl) else 0.0,
            }
        )
    return pd.DataFrame(rows)
