"""Causal rolling LONG/SHORT direction tracker for paired walk-forward research.

The tracker is deliberately research-only. It consumes immutable paired
`WALK_FORWARD` observations and scores each candidate strictly from earlier
resolved candidates. A prior pair is eligible only when both LONG and SHORT
outcomes were already closed before the current candidate entry time. No
current-candidate outcome is added to history until all feature and family votes
for that candidate have been frozen.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable

import numpy as np
import pandas as pd


LONG = "LONG"
SHORT = "SHORT"
NEUTRAL = "NEUTRAL"
TIE = "TIE"

DIRECTION_TRACKER_VERSION = "WALK_FORWARD_DIRECTION_TRACKER_V1"
LONG_THRESHOLD = 0.60
SHORT_THRESHOLD = 0.40

FeatureExtractor = Callable[[pd.Series], Any]


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    result = str(value).strip().upper()
    if not result or result in {"UNKNOWN", "NONE", "NAN", "<NA>"}:
        return None
    return result


def _number(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _bool(value: Any) -> bool | None:
    if _is_missing(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _column(name: str) -> FeatureExtractor:
    return lambda row: _text(row.get(name))


def _bucket(
    name: str,
    cutpoints: tuple[float, ...],
    labels: tuple[str, ...],
) -> FeatureExtractor:
    if len(labels) != len(cutpoints) + 1:
        raise ValueError("bucket labels must be one longer than cutpoints")

    def extract(row: pd.Series) -> str | None:
        value = _number(row.get(name))
        if value is None:
            return None
        for index, cutpoint in enumerate(cutpoints):
            if value < cutpoint:
                return labels[index]
        return labels[-1]

    return extract


def _signed_state(name: str, epsilon: float = 0.0) -> FeatureExtractor:
    def extract(row: pd.Series) -> str | None:
        value = _number(row.get(name))
        if value is None:
            return None
        if value > epsilon:
            return "POS"
        if value < -epsilon:
            return "NEG"
        return "FLAT"

    return extract


def _di_direction(row: pd.Series) -> str | None:
    plus_di = _number(row.get("plus_di"))
    minus_di = _number(row.get("minus_di"))
    if plus_di is None or minus_di is None:
        return None
    if plus_di > minus_di:
        return "PLUS_GT_MINUS"
    if minus_di > plus_di:
        return "MINUS_GT_PLUS"
    return "EQUAL"


def _ema_price_vs_100(row: pd.Series) -> str | None:
    price = _number(row.get("signal_close_price"))
    ema100 = _number(row.get("ema_100"))
    if price is None or ema100 is None:
        return None
    if price > ema100:
        return "ABOVE"
    if price < ema100:
        return "BELOW"
    return "AT"


def _ema_order(row: pd.Series) -> str | None:
    ema50 = _number(row.get("ema_50"))
    ema100 = _number(row.get("ema_100"))
    ema200 = _number(row.get("ema_200"))
    if ema50 is None or ema100 is None or ema200 is None:
        return None
    if ema50 > ema100 > ema200:
        return "BULL_STACK"
    if ema50 < ema100 < ema200:
        return "BEAR_STACK"
    return "MIXED"


def _funding_extreme(row: pd.Series) -> str | None:
    positive = _bool(row.get("funding_extreme_positive"))
    negative = _bool(row.get("funding_extreme_negative"))
    if positive:
        return "EXTREME_POS"
    if negative:
        return "EXTREME_NEG"
    if positive is None and negative is None:
        return None
    return "NORMAL"


FEATURES: tuple[tuple[str, str, FeatureExtractor], ...] = (
    ("MARKET_REGIME", "market_regime", _column("market_regime")),
    ("DI_DIRECTION", "di_direction", _di_direction),
    ("DI_PRESSURE", "di_pressure", _column("di_pressure_state")),
    (
        "ADX_TREND_STRENGTH",
        "adx_bucket",
        _bucket("adx", (20.0, 30.0, 40.0), ("LT20", "20_30", "30_40", "GE40")),
    ),
    ("MEAN_REVERSION", "mr_state", _column("mean_reversion_state")),
    ("MEAN_REVERSION", "mr_motion", _column("mean_reversion_motion")),
    (
        "RSI",
        "rsi_bucket",
        _bucket(
            "entry_rsi",
            (30.0, 40.0, 50.0, 60.0, 70.0),
            ("LT30", "30_40", "40_50", "50_60", "60_70", "GE70"),
        ),
    ),
    ("ICHIMOKU_4H", "tk_state", _column("tk_state")),
    ("ICHIMOKU_4H", "price_vs_cloud", _column("price_vs_cloud")),
    ("ICHIMOKU_4H", "future_cloud", _column("future_cloud_state")),
    ("ICHIMOKU_4H", "kijun_slope", _signed_state("kijun_slope_atr", 0.05)),
    ("ICHIMOKU_1D", "tk_state_1d", _column("ich_1d_tk_state")),
    (
        "ICHIMOKU_1D",
        "price_vs_cloud_1d",
        _column("ich_1d_price_vs_cloud"),
    ),
    (
        "ICHIMOKU_1D",
        "future_cloud_1d",
        _column("ich_1d_future_cloud_state"),
    ),
    (
        "ICHIMOKU_1D",
        "kijun_slope_1d",
        _signed_state("ich_1d_kijun_slope_atr", 0.05),
    ),
    ("EMA_STRUCTURE", "price_vs_ema100", _ema_price_vs_100),
    ("EMA_STRUCTURE", "ema_order", _ema_order),
    ("MACD", "cross_state", _column("macd_cross_state")),
    ("MACD", "zero_state", _column("macd_zero_state")),
    (
        "ATR_VOLATILITY",
        "atr_pct_bucket",
        _bucket(
            "atr_pct",
            (0.01, 0.02, 0.03),
            ("LT1PCT", "1_2PCT", "2_3PCT", "GE3PCT"),
        ),
    ),
    ("BB_VOLATILITY", "bb_width_direction", _signed_state("bb_width_change")),
    ("OI_POSITIONING", "price_oi_state", _column("price_oi_state")),
    ("OI_POSITIONING", "oi_change_1h", _signed_state("oi_change_pct_1h", 0.001)),
    ("FUNDING_BASIS", "funding_bias", _column("funding_bias")),
    ("FUNDING_BASIS", "funding_extreme", _funding_extreme),
    ("FUNDING_BASIS", "basis_state", _column("mark_index_basis_state")),
    ("TAKER_FLOW", "taker_base", _signed_state("taker_delta_pct")),
    ("TAKER_FLOW", "taker_15m", _signed_state("taker_delta_pct_15m")),
    ("TAKER_FLOW", "taker_1h", _signed_state("taker_delta_pct_1h")),
)


def _history_vote(
    history: list[tuple[pd.Timestamp, int, str]],
    lookback: int,
    *,
    candidate_entry_time: pd.Timestamp,
) -> tuple[int, int, int, float | None, str]:
    # Only outcomes already fully resolved before the candidate becomes
    # decision-available may contribute.  Keep occurrence order by the original
    # research signal index after filtering on the causal availability watermark.
    eligible = [
        (signal_index, winner)
        for available_time, signal_index, winner in history
        if available_time < candidate_entry_time
    ]
    eligible.sort(key=lambda item: item[0])
    observations = [winner for _, winner in eligible[-lookback:]]
    long_count = sum(value == LONG for value in observations)
    short_count = sum(value == SHORT for value in observations)
    directional = long_count + short_count
    if directional == 0:
        return long_count, short_count, 0, None, NEUTRAL
    long_share = long_count / directional
    if long_share > LONG_THRESHOLD:
        vote = LONG
    elif long_share < SHORT_THRESHOLD:
        vote = SHORT
    else:
        vote = NEUTRAL
    return long_count, short_count, directional, long_share, vote


def _aggregate_votes(votes: list[str]) -> tuple[int, int, float | None, str]:
    long_count = sum(value == LONG for value in votes)
    short_count = sum(value == SHORT for value in votes)
    directional = long_count + short_count
    if directional == 0:
        return 0, 0, None, NEUTRAL
    long_share = long_count / directional
    if long_share > LONG_THRESHOLD:
        decision = LONG
    elif long_share < SHORT_THRESHOLD:
        decision = SHORT
    else:
        decision = NEUTRAL
    return long_count, short_count, long_share, decision


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError(f"{name} is missing")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _pair_table(
    samples: pd.DataFrame,
) -> list[tuple[pd.Series, str, float, float, pd.Timestamp, pd.Timestamp]]:
    required = {
        "walk_forward_candidate_id",
        "research_signal_index",
        "side",
        "entry_time",
        "exit_time",
        "pair_net_r",
    }
    missing = sorted(required - set(samples.columns))
    if missing:
        raise ValueError(
            "direction tracker requires paired WALK_FORWARD columns: "
            + ", ".join(missing)
        )

    rows: list[
        tuple[pd.Series, str, float, float, pd.Timestamp, pd.Timestamp]
    ] = []
    grouped = samples.groupby("walk_forward_candidate_id", sort=False)
    for candidate_id, group in grouped:
        sides = group["side"].astype(str).str.upper()
        if len(group) != 2 or set(sides) != {LONG, SHORT}:
            raise ValueError(
                f"candidate {candidate_id!r} must contain exactly one LONG and one SHORT row"
            )
        long_row = group.loc[sides == LONG].iloc[0]
        short_row = group.loc[sides == SHORT].iloc[0]
        long_r = _number(long_row.get("pair_net_r"))
        short_r = _number(short_row.get("pair_net_r"))
        if long_r is None or short_r is None:
            raise ValueError(f"candidate {candidate_id!r} is missing pair_net_r")

        long_entry = _utc_timestamp(long_row.get("entry_time"), "LONG entry_time")
        short_entry = _utc_timestamp(short_row.get("entry_time"), "SHORT entry_time")
        if long_entry != short_entry:
            raise ValueError(
                f"candidate {candidate_id!r} LONG/SHORT rows disagree on entry_time"
            )
        long_exit = _utc_timestamp(long_row.get("exit_time"), "LONG exit_time")
        short_exit = _utc_timestamp(short_row.get("exit_time"), "SHORT exit_time")
        if long_exit < long_entry or short_exit < short_entry:
            raise ValueError(f"candidate {candidate_id!r} contains exit-before-entry")
        pair_available_time = max(long_exit, short_exit)
        rows.append(
            (
                long_row,
                str(candidate_id),
                long_r,
                short_r,
                long_entry,
                pair_available_time,
            )
        )

    rows.sort(
        key=lambda item: (
            item[4],
            int(item[0]["research_signal_index"]),
            item[1],
        )
    )
    return rows


def build_walk_forward_direction_tracker(
    samples: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return feature-detail rows, candidate scores, and a compact summary.

    Feature states are read from the canonical LONG row of each immutable pair so
    direction-relative fields (for example DI pressure) have one stable
    orientation across history. The outcome still compares the actual LONG and
    SHORT pair_net_r values.
    """

    # Keep all observed state outcomes with their pair-resolution watermark.
    # Eligibility for candidate N is decided at read time from entry_time, not
    # merely from signal order, so overlapping still-open candidates cannot leak.
    histories: dict[
        tuple[str, str], list[tuple[pd.Timestamp, int, str]]
    ] = defaultdict(list)
    detail_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []

    for sequence, (
        context,
        candidate_id,
        long_r,
        short_r,
        candidate_entry_time,
        pair_available_time,
    ) in enumerate(_pair_table(samples), start=1):
        winner = LONG if long_r > short_r else SHORT if short_r > long_r else TIE
        feature_votes_100: dict[str, list[str]] = defaultdict(list)
        feature_votes_20: dict[str, list[str]] = defaultdict(list)
        current_states: list[tuple[str, str]] = []

        for family, feature, extractor in FEATURES:
            state = extractor(context)
            if state is None:
                continue
            state = str(state)
            key = (feature, state)
            current_states.append(key)
            history = histories[key]
            l100, s100, n100, share100, vote100 = _history_vote(
                history,
                100,
                candidate_entry_time=candidate_entry_time,
            )
            l20, s20, n20, share20, vote20 = _history_vote(
                history,
                20,
                candidate_entry_time=candidate_entry_time,
            )
            feature_votes_100[family].append(vote100)
            feature_votes_20[family].append(vote20)
            detail_rows.append(
                {
                    "tracker_version": DIRECTION_TRACKER_VERSION,
                    "sequence": sequence,
                    "walk_forward_candidate_id": candidate_id,
                    "research_signal_index": int(context["research_signal_index"]),
                    "candidate_entry_time": candidate_entry_time,
                    "pair_available_time": pair_available_time,
                    "family": family,
                    "feature": feature,
                    "state": state,
                    "winner": winner,
                    "long_r": long_r,
                    "short_r": short_r,
                    "last100_long_count": l100,
                    "last100_short_count": s100,
                    "last100_directional_count": n100,
                    "last100_long_share": share100,
                    "last100_vote": vote100,
                    "last20_long_count": l20,
                    "last20_short_count": s20,
                    "last20_directional_count": n20,
                    "last20_long_share": share20,
                    "last20_vote": vote20,
                }
            )

        families = sorted(set(feature_votes_100) | set(feature_votes_20))
        family_result_100: dict[str, str] = {}
        family_result_20: dict[str, str] = {}
        for family in families:
            _, _, _, family_result_100[family] = _aggregate_votes(
                feature_votes_100.get(family, [])
            )
            _, _, _, family_result_20[family] = _aggregate_votes(
                feature_votes_20.get(family, [])
            )

        long100, short100, share100, decision100 = _aggregate_votes(
            list(family_result_100.values())
        )
        long20, short20, share20, decision20 = _aggregate_votes(
            list(family_result_20.values())
        )
        agreed = (
            decision100
            if decision100 == decision20 and decision100 in {LONG, SHORT}
            else NEUTRAL
        )

        score: dict[str, Any] = {
            "tracker_version": DIRECTION_TRACKER_VERSION,
            "sequence": sequence,
            "walk_forward_candidate_id": candidate_id,
            "research_signal_index": int(context["research_signal_index"]),
            "candidate_entry_time": candidate_entry_time,
            "pair_available_time": pair_available_time,
            "winner": winner,
            "long_r": long_r,
            "short_r": short_r,
            "last100_long_family_votes": long100,
            "last100_short_family_votes": short100,
            "last100_long_share": share100,
            "last100_decision": decision100,
            "last20_long_family_votes": long20,
            "last20_short_family_votes": short20,
            "last20_long_share": share20,
            "last20_decision": decision20,
            "agreed_decision": agreed,
            "agreement_correct": agreed == winner if agreed != NEUTRAL else False,
        }
        for family in families:
            safe = family.lower()
            score[f"{safe}_last100_vote"] = family_result_100[family]
            score[f"{safe}_last20_vote"] = family_result_20[family]
        score_rows.append(score)

        # Store the outcome only after every score is frozen.  Future candidates
        # still cannot consume it until BOTH paired sides have closed strictly
        # before that future candidate's entry_time.
        signal_index = int(context["research_signal_index"])
        for key in current_states:
            histories[key].append((pair_available_time, signal_index, winner))

    details = pd.DataFrame(detail_rows)
    scores = pd.DataFrame(score_rows)
    total = len(scores)
    agreed_mask = scores["agreed_decision"].isin([LONG, SHORT]) if total else pd.Series(dtype=bool)
    agreement_count = int(agreed_mask.sum()) if total else 0
    correct = int(scores.loc[agreed_mask, "agreement_correct"].sum()) if agreement_count else 0
    summary = {
        "tracker_version": DIRECTION_TRACKER_VERSION,
        "thresholds": {
            "long": f">{LONG_THRESHOLD:.2f}",
            "short": f"<{SHORT_THRESHOLD:.2f}",
            "neutral": f"{SHORT_THRESHOLD:.2f}..{LONG_THRESHOLD:.2f} inclusive",
        },
        "history_windows": [100, 20],
        "final_policy": "REQUIRE_LAST100_AND_LAST20_SAME_DIRECTION",
        "total_candidates": total,
        "agreement_candidates": agreement_count,
        "coverage_pct": (100.0 * agreement_count / total) if total else None,
        "agreement_correct": correct,
        "agreement_accuracy_pct": (
            100.0 * correct / agreement_count if agreement_count else None
        ),
        "long_agreements": (
            int((scores["agreed_decision"] == LONG).sum()) if total else 0
        ),
        "short_agreements": (
            int((scores["agreed_decision"] == SHORT).sum()) if total else 0
        ),
        "causal": True,
        "current_candidate_excluded_from_own_history": True,
        "history_requires_fully_closed_pair_before_candidate": True,
        "pair_available_time": "MAX_LONG_SHORT_EXIT_TIME",
        "history_availability_rule": "pair_available_time < candidate_entry_time",
        "context_orientation": "CANONICAL_LONG_ROW",
        "feature_families": sorted({family for family, _, _ in FEATURES}),
    }
    return details, scores, summary
