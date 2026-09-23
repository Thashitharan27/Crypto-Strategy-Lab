"""Canonical activation contract for adaptive weekly walk-forward research.

This module is intentionally policy-only: it validates/normalizes configuration
but never changes causal rules or performs optimization.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ADAPTIVE_WEEKLY_OBJECTIVE = "NEXT_WEEK_OOS"
ADAPTIVE_WEEKLY_DEFAULTS = {
    "enabled": True,
    "primary_lookback_weeks": 1,
    "context_lookback_weeks": 4,
    "objective": ADAPTIVE_WEEKLY_OBJECTIVE,
    "allow_keep": True,
    "allow_refine": True,
    "allow_retire": True,
    "allow_replace": True,
    "allow_flip": True,
    "benchmark_raw_strategy": True,
    "track_adaptation_lag": True,
    "track_rule_half_life": True,
}


def normalize_adaptive_weekly(value: Any) -> dict[str, Any] | None:
    """Return the canonical adaptive object or None when disabled.

    Legacy adaptive=true remains accepted and is normalized to the native
    object contract. The object form is authoritative for new experiments.
    """
    if value in (None, False):
        return None
    if value is True:
        return deepcopy(ADAPTIVE_WEEKLY_DEFAULTS)
    if not isinstance(value, dict):
        raise ValueError("rule_update_policy.adaptive must be boolean or an object")

    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("rule_update_policy.adaptive.enabled must be boolean")
    if not enabled:
        return None

    normalized = deepcopy(ADAPTIVE_WEEKLY_DEFAULTS)
    normalized.update(deepcopy(value))
    normalized["enabled"] = True

    for key in ("primary_lookback_weeks", "context_lookback_weeks"):
        raw = normalized.get(key)
        if isinstance(raw, bool):
            raise ValueError(f"rule_update_policy.adaptive.{key} must be an integer")
        try:
            number = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"rule_update_policy.adaptive.{key} must be an integer"
            ) from exc
        if not 1 <= number <= 104:
            raise ValueError(
                f"rule_update_policy.adaptive.{key} must be between 1 and 104"
            )
        normalized[key] = number

    if normalized["context_lookback_weeks"] < normalized["primary_lookback_weeks"]:
        raise ValueError(
            "rule_update_policy.adaptive.context_lookback_weeks must be >= "
            "primary_lookback_weeks"
        )

    objective = str(normalized.get("objective") or "").strip().upper()
    if objective != ADAPTIVE_WEEKLY_OBJECTIVE:
        raise ValueError(
            "rule_update_policy.adaptive.objective must be NEXT_WEEK_OOS"
        )
    normalized["objective"] = objective

    for key in (
        "allow_keep",
        "allow_refine",
        "allow_retire",
        "allow_replace",
        "allow_flip",
        "benchmark_raw_strategy",
        "track_adaptation_lag",
        "track_rule_half_life",
    ):
        raw = normalized.get(key)
        if not isinstance(raw, bool):
            raise ValueError(f"rule_update_policy.adaptive.{key} must be boolean")

    allowed = set(ADAPTIVE_WEEKLY_DEFAULTS)
    unknown = sorted(set(normalized) - allowed)
    if unknown:
        raise ValueError(
            "unsupported rule_update_policy.adaptive fields: " + ", ".join(unknown)
        )
    return normalized


def adaptive_weekly_policy(rule_update_policy: dict[str, Any] | None) -> dict[str, Any] | None:
    """Read a normalized or legacy policy without mutating it."""
    if not isinstance(rule_update_policy, dict):
        return None
    mode = str(rule_update_policy.get("mode") or "").strip().upper()
    if mode != "WEEKLY_BATCH_OOS":
        return None
    return normalize_adaptive_weekly(rule_update_policy.get("adaptive"))
