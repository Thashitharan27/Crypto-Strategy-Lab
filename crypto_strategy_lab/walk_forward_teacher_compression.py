"""Deterministic episode/phase compression for causal teacher learning.

Every immutable WALK_FORWARD source observation remains in the reference artifacts.
This module only decides whether one already-resolved teacher observation needs a
new ChatGPT learning review.

Compression is deliberately conservative:
- research_episode_id scopes comparisons but never causes a skip by itself;
- fingerprints use coarse, entry-time structural buckets;
- comparisons are against the last *surfaced* teacher in the episode;
- outcome contradictions, active-rule failures, structural changes, and the
  first confirmation after newly learned rules always surface;
- legacy reviewed teachers without an audit fingerprint force a new surfaced
  baseline rather than retroactively changing experiment semantics.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


TEACHER_COMPRESSION_CONTRACT = "causal_teacher_phase_compression_v1"

AUTO_COMPRESSED_STATUS = "AUTO_COMPRESSED"
CHATGPT_REVIEWED_STATUS = "CHATGPT_REVIEWED"

RULE_EVENT_TYPES = frozenset(
    {"ENTRY_LEARNED", "ENTRY_REFINED", "VETO_LEARNED", "FLIP_LEARNED"}
)


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _numeric_bucket(
    value: Any,
    cuts: tuple[float, ...],
    labels: tuple[str, ...],
    *,
    missing: str = "UNKNOWN",
) -> str:
    number = _number(value)
    if number is None:
        return missing
    for cut, label in zip(cuts, labels):
        if number < cut:
            return label
    return labels[-1]


def _di_ratio_bucket(value: Any) -> str:
    return _numeric_bucket(
        value,
        (1.0, 1.5, 2.0, 3.0, 5.0),
        ("LT_1", "1_TO_1_5", "1_5_TO_2", "2_TO_3", "3_TO_5", "GE_5"),
    )


def _adx_bucket(value: Any) -> str:
    return _numeric_bucket(
        value,
        (20.0, 30.0, 40.0, 55.0),
        ("LT_20", "20_TO_30", "30_TO_40", "40_TO_55", "GE_55"),
    )


def _extension_bucket(value: Any) -> str:
    return _numeric_bucket(
        value,
        (-1.0, 0.0, 1.0, 2.0, 3.0, 4.0),
        (
            "LE_NEG_1",
            "NEG_1_TO_0",
            "0_TO_1",
            "1_TO_2",
            "2_TO_3",
            "3_TO_4",
            "GE_4",
        ),
    )


def _room_bucket(value: Any) -> str:
    return _numeric_bucket(
        value,
        (0.0, 0.25, 0.5, 0.75, 1.0, 1.5),
        (
            "NEGATIVE",
            "0_TO_0_25",
            "0_25_TO_0_5",
            "0_5_TO_0_75",
            "0_75_TO_1",
            "1_TO_1_5",
            "GE_1_5",
        ),
    )


def _momentum_bucket(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "UNKNOWN"
    if number > 0.001:
        return "POSITIVE"
    if number < -0.001:
        return "NEGATIVE"
    return "FLAT"


def _sign_bucket(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "UNKNOWN"
    if number > 0:
        return "POSITIVE"
    if number < 0:
        return "NEGATIVE"
    return "ZERO"


def _paired_outcome_class(teacher: dict[str, Any]) -> str:
    number = _number(teacher.get("paired_opposite_net_r"))
    if number is None:
        return "UNAVAILABLE"
    if number > 0:
        return "WIN"
    if number < 0:
        return "LOSS"
    return "BREAKEVEN"


def _active_rule_versions(packet: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    rows = packet.get("active_rule_versions") or []
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        rule_id = str(row.get("rule_id") or "").strip()
        version = str(row.get("rule_version") or "").strip()
        if rule_id:
            result[rule_id] = version
    return result


def _rule_signature(packet: dict[str, Any]) -> dict[str, Any]:
    coverage = packet.get("current_rule_coverage") or {}
    if not isinstance(coverage, dict):
        coverage = {}
    versions = _active_rule_versions(packet)

    def versioned(family: str, key: str) -> list[str]:
        values = coverage.get(key) or []
        if not isinstance(values, (list, tuple)):
            values = []
        output = []
        for raw in values:
            rule_id = str(raw or "").strip()
            if not rule_id:
                continue
            version = versions.get(rule_id)
            output.append(
                f"{family}:{rule_id}@{version}" if version else f"{family}:{rule_id}"
            )
        return sorted(set(output))

    matches = [
        *versioned("ENTRY", "matched_entry_groups"),
        *versioned("VETO", "matched_veto_groups"),
        *versioned("FLIP", "matched_flip_groups"),
    ]
    return {
        "eligible": bool(coverage.get("eligible", False)),
        "reason": _upper(coverage.get("reason")),
        "rule_effective_side": _upper(coverage.get("rule_effective_side")),
        "matches": matches,
    }


def _directional_di_ratio(trade: dict[str, Any], side: str) -> float | None:
    direct = _number(trade.get("directional_di"))
    opposing = _number(trade.get("opposing_di"))
    if direct is not None and opposing is not None and opposing > 0:
        return direct / opposing
    ratio = _number(trade.get("di_ratio"))
    if ratio is not None:
        return ratio
    plus = _number(trade.get("plus_di"))
    minus = _number(trade.get("minus_di"))
    if plus is None or minus is None:
        return None
    numerator, denominator = (plus, minus) if side == "LONG" else (minus, plus)
    return numerator / denominator if denominator > 0 else None


def _directional_ema50_extension(trade: dict[str, Any], side: str) -> float | None:
    value = _number(trade.get("ema_50_distance_atr"))
    if value is None:
        return None
    return value if side == "LONG" else -value


def _sr_components(entry_context: dict[str, Any]) -> dict[str, Any]:
    block = entry_context.get("support_resistance_trade_context_v2") or {}
    timeframes = block.get("timeframes") or {}
    result: dict[str, Any] = {}
    for label in ("STRATEGY_TF", "1H", "4H", "1D"):
        values = timeframes.get(label) or {}
        if not isinstance(values, dict):
            values = {}
        result[label] = {
            "entry_relation": _upper(values.get("entry_relation")),
            "opposing_structure_state": _upper(
                values.get("opposing_structure_state")
            ),
            "favorable_structure_state": _upper(
                values.get("favorable_structure_state")
            ),
            "target_path": _upper(values.get("target_path")),
            "opposing_room_target_bucket": _room_bucket(
                values.get("opposing_room_target_multiple")
            ),
        }
    return result


def _role_reversal_components(feature: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in feature.items():
        name = str(key)
        if "role_reversal_state" not in name.lower():
            continue
        result[name] = _upper(value)
    return dict(sorted(result.items()))


def _ichimoku_structure(feature: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    interesting_suffixes = (
        "price_vs_cloud",
        "future_cloud_state",
        "current_cloud_state",
    )
    for key, value in feature.items():
        name = str(key)
        lower = name.lower()
        if not lower.startswith("ich_") and not lower.startswith("ichimoku_"):
            continue
        if not lower.endswith(interesting_suffixes):
            continue
        result[name] = _upper(value)
    return dict(sorted(result.items()))


def _setup_classification(
    *,
    side: str,
    di_state: str,
    di_ratio: float | None,
    adx: float | None,
    extension: float | None,
    macd_histogram: float | None,
    sr: dict[str, Any],
    role_reversal: dict[str, str],
) -> str:
    role_states = set(role_reversal.values())
    breakout_states = {
        "BREAKOUT_CONFIRMED",
        "RETEST_APPROACHING",
        "RETESTING_FROM_BREAK_SIDE",
        "VALID_RETEST",
        "RETEST_HELD",
    }
    if role_states & breakout_states:
        return "BREAKOUT_RECLAIM"

    macd_opposes = (
        (side == "LONG" and macd_histogram is not None and macd_histogram < 0)
        or (side == "SHORT" and macd_histogram is not None and macd_histogram > 0)
    )
    if (
        extension is not None
        and extension >= 3.0
        and adx is not None
        and adx >= 40.0
        and di_state in {"CONTRACTING", "MIXED"}
        and macd_opposes
    ):
        return "EXHAUSTION"

    if (
        di_state == "EXPANDING"
        and di_ratio is not None
        and di_ratio >= 1.5
    ):
        return "CONTINUATION"

    strategy_relation = (
        (sr.get("STRATEGY_TF") or {}).get("entry_relation") or "UNKNOWN"
    )
    if strategy_relation in {
        "INSIDE_FAVORABLE_ZONE",
        "NEAR_FAVORABLE_STRUCTURE",
        "FAVORABLE_STRUCTURE_ONLY",
    }:
        return "PULLBACK"

    return "OTHER"


def build_teacher_phase_audit(packet: dict[str, Any]) -> dict[str, Any]:
    """Build a causal coarse fingerprint from one hydrated teacher packet."""
    teacher = packet.get("teacher") or {}
    entry_context = packet.get("entry_context") or {}
    trade = entry_context.get("trade_entry_context") or {}
    feature = entry_context.get("feature_context") or {}
    if not isinstance(teacher, dict):
        teacher = {}
    if not isinstance(trade, dict):
        trade = {}
    if not isinstance(feature, dict):
        feature = {}

    side = _upper(teacher.get("side") or trade.get("side"))
    profile = str(
        teacher.get("strategy_profile_key")
        or trade.get("strategy_profile_key")
        or ""
    ).strip().lower()
    episode_id = str(
        teacher.get("research_episode_id")
        or trade.get("research_episode_id")
        or ""
    ).strip()

    di_state = _upper(
        trade.get("di_pressure_state")
        or trade.get(
            "long_di_pressure_state" if side == "LONG" else "short_di_pressure_state"
        )
    )
    di_ratio = _directional_di_ratio(trade, side)
    adx = _number(trade.get("adx"))
    extension = _directional_ema50_extension(trade, side)
    macd_histogram = _number(trade.get("macd_histogram"))
    sr = _sr_components(entry_context)
    role_reversal = _role_reversal_components(feature)
    ichimoku = _ichimoku_structure(feature)
    rule_signature = _rule_signature(packet)

    structural_components = {
        "profile": profile,
        "source_side": side,
        "di_pressure_state": di_state,
        "di_ratio_bucket": _di_ratio_bucket(di_ratio),
        "adx_bucket": _adx_bucket(adx),
        "ema50_directional_extension_bucket": _extension_bucket(extension),
        "macd_histogram_sign": _sign_bucket(macd_histogram),
        "macd_histogram_change_sign": _sign_bucket(
            trade.get("macd_histogram_change")
        ),
        "momentum_state": _momentum_bucket(
            trade.get("directional_momentum_return_at_entry")
            or trade.get("momentum")
        ),
        "support_resistance": sr,
        "role_reversal": role_reversal,
        "ichimoku_structure": ichimoku,
    }
    structural_components["setup_classification"] = _setup_classification(
        side=side,
        di_state=di_state,
        di_ratio=di_ratio,
        adx=adx,
        extension=extension,
        macd_histogram=macd_histogram,
        sr=sr,
        role_reversal=role_reversal,
    )

    phase_components = {
        **structural_components,
        "source_outcome_class": _upper(teacher.get("result")),
        "paired_outcome_class": _paired_outcome_class(teacher),
        "active_rule_signature": rule_signature,
    }

    return {
        "contract": TEACHER_COMPRESSION_CONTRACT,
        "episode_id": episode_id or None,
        "teacher_id": (
            str(
                teacher.get("pair_id")
                or teacher.get("walk_forward_candidate_id")
                or ""
            ).strip()
            or None
        ),
        "structural_phase": structural_components["setup_classification"],
        "structural_fingerprint": _hash(structural_components),
        "phase_fingerprint": _hash(phase_components),
        "source_outcome_class": phase_components["source_outcome_class"],
        "paired_outcome_class": phase_components["paired_outcome_class"],
        "active_rule_matches": list(rule_signature["matches"]),
        "active_rule_signature": rule_signature,
        "structural_components": structural_components,
    }


def _teacher_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("pair_id")
        or payload.get("walk_forward_candidate_id")
        or ""
    ).strip()


def _reviewed_teacher_events(
    events: list[dict[str, Any]], episode_id: str
) -> list[dict[str, Any]]:
    result = []
    for event in events:
        if event.get("event_type") != "TEACHER_RESOLVED":
            continue
        payload = event.get("payload") or {}
        if str(payload.get("research_episode_id") or "").strip() != episode_id:
            continue
        if _upper(payload.get("teacher_review_status"), "") == AUTO_COMPRESSED_STATUS:
            continue
        result.append(event)
    return result


def _rules_learned_immediately_after(
    events: list[dict[str, Any]], teacher_event: dict[str, Any]
) -> list[str]:
    try:
        start_sequence = int(teacher_event.get("sequence", 0))
    except (TypeError, ValueError):
        return []
    rule_ids: list[str] = []
    started = False
    for event in events:
        try:
            sequence = int(event.get("sequence", 0))
        except (TypeError, ValueError):
            continue
        if sequence <= start_sequence:
            continue
        event_type = str(event.get("event_type") or "").upper()
        if event_type in RULE_EVENT_TYPES:
            started = True
            rule_id = str((event.get("payload") or {}).get("rule_id") or "").strip()
            if rule_id:
                rule_ids.append(rule_id)
            continue
        if started or event_type == "TEACHER_RESOLVED":
            break
        # Atomic teacher-review batches place rule events immediately after the
        # teacher event. If any unrelated event appears first, there was no rule.
        break
    return sorted(set(rule_ids))


def _confirmation_consumed(
    events: list[dict[str, Any]], teacher_id: str
) -> bool:
    if not teacher_id:
        return False
    for event in events:
        if event.get("event_type") != "TEACHER_RESOLVED":
            continue
        payload = event.get("payload") or {}
        if str(payload.get("confirmation_of_teacher_id") or "").strip() == teacher_id:
            return True
    return False


def teacher_compression_decision(
    packet: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return SURFACE or AUTO_COMPRESS for one resolved teacher observation."""
    audit = build_teacher_phase_audit(packet)
    result: dict[str, Any] = {
        "contract": TEACHER_COMPRESSION_CONTRACT,
        "action": "SURFACE",
        "reason": "CONSERVATIVE_DEFAULT",
        "audit": audit,
        "compared_to_teacher_id": None,
        "confirmation_of_teacher_id": None,
        "confirmation_rule_ids": [],
    }

    episode_id = str(audit.get("episode_id") or "").strip()
    if not episode_id:
        result["reason"] = "EPISODE_ID_UNAVAILABLE"
        return result

    prior = _reviewed_teacher_events(events, episode_id)
    if not prior:
        result["reason"] = "FIRST_SURFACED_TEACHER_IN_EPISODE"
        return result

    previous_event = prior[-1]
    previous = previous_event.get("payload") or {}
    previous_id = _teacher_id(previous)
    result["compared_to_teacher_id"] = previous_id or None
    previous_audit = previous.get("teacher_phase_audit")
    if (
        not isinstance(previous_audit, dict)
        or not previous_audit.get("structural_fingerprint")
        or not previous_audit.get("phase_fingerprint")
    ):
        result["reason"] = "LEGACY_PHASE_BASELINE_REQUIRED"
        return result

    current_outcome = _upper(audit.get("source_outcome_class"))
    previous_outcome = _upper(previous_audit.get("source_outcome_class"))
    if current_outcome != previous_outcome:
        result["reason"] = "OUTCOME_CLASS_CHANGED"
        return result

    current_paired = _upper(audit.get("paired_outcome_class"))
    previous_paired = _upper(previous_audit.get("paired_outcome_class"))
    if (
        current_paired != "UNAVAILABLE"
        and previous_paired != "UNAVAILABLE"
        and current_paired != previous_paired
    ):
        result["reason"] = "PAIRED_OUTCOME_CLASS_CHANGED"
        return result

    teacher = packet.get("teacher") or {}
    coverage = packet.get("current_rule_coverage") or {}
    if not isinstance(coverage, dict):
        coverage = {}
    active_matches = set(audit.get("active_rule_matches") or [])
    matched_entry_or_flip = any(
        value.startswith("ENTRY:") or value.startswith("FLIP:")
        for value in active_matches
    )
    source_side = _upper(teacher.get("side"))
    effective_side = _upper(coverage.get("rule_effective_side"))
    effective_outcome = current_outcome
    if (
        source_side in {"LONG", "SHORT"}
        and effective_side in {"LONG", "SHORT"}
        and effective_side != source_side
    ):
        effective_outcome = current_paired

    if (
        bool(coverage.get("eligible", False))
        and matched_entry_or_flip
        and effective_outcome in {"LOSS", "BREAKEVEN"}
    ):
        result["reason"] = "ACTIVE_RULE_FAILURE"
        return result

    if (
        current_outcome == "WIN"
        and source_side in {"LONG", "SHORT"}
        and effective_side in {"LONG", "SHORT"}
        and effective_side != source_side
        and effective_outcome == "UNAVAILABLE"
    ):
        result["reason"] = "ACTIVE_RULE_DIRECTION_CONFLICT"
        return result

    if (
        audit.get("structural_fingerprint")
        != previous_audit.get("structural_fingerprint")
    ):
        result["reason"] = "STRUCTURAL_PHASE_CHANGED"
        return result

    learned_rule_ids = _rules_learned_immediately_after(events, previous_event)
    if learned_rule_ids and not _confirmation_consumed(events, previous_id):
        current_match_ids = {
            token.split(":", 1)[1].split("@", 1)[0]
            for token in active_matches
            if ":" in token
        }
        result["confirmation_of_teacher_id"] = previous_id or None
        result["confirmation_rule_ids"] = learned_rule_ids
        if current_match_ids.intersection(learned_rule_ids):
            result["reason"] = "FIRST_RULE_CONFIRMATION_REQUIRED"
        else:
            result["reason"] = "LEARNED_RULE_PHASE_MISS"
        return result

    if (
        audit.get("active_rule_signature")
        != previous_audit.get("active_rule_signature")
    ):
        result["reason"] = "ACTIVE_RULE_SET_CHANGED"
        return result

    previous_confirmation_target = str(
        previous.get("confirmation_of_teacher_id") or ""
    ).strip()
    result["action"] = "AUTO_COMPRESS"
    if previous_confirmation_target:
        result["reason"] = "POST_CONFIRMATION_REPEAT"
    elif active_matches:
        result["reason"] = "RULE_PHASE_REPEAT"
    else:
        result["reason"] = "CORRELATED_PHASE_DUPLICATE"
    return result
