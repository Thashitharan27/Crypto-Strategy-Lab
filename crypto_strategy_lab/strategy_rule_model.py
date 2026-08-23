"""Rule-based strategy authoring compiled to the mature simulator contract.

The researcher-facing model is intentionally not profile based. Market
permissions, required filters, vetoes, and optional direction flips are authored
once with regime/side scopes. Only at the simulator boundary are those rules
expanded into the six mature regime/direction inputs still consumed by the proven
engine. Builder metadata is embedded in rule dictionaries so save/load can round
trip the rule model without exposing profiles in the UI.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

from crypto_strategy_lab.data_lake_config import (
    ExecutionProfileConfig,
    StrategyProfileConfig,
)
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, RULE_INDICATORS

# Direction selection and trade permission are intentionally separate concepts.
# DI is the only currently researched native direction strategy. Additional
# direction strategies can be added here later when they have a real native
# implementation; LONG/SHORT selection belongs to MARKET_PERMISSIONS below.
DIRECTION_MODES = ("DI",)
REGIMES = ("BULL", "BEAR", "SIDEWAYS")
SIDES = ("LONG", "SHORT")
MARKET_PERMISSIONS = tuple(f"{regime}_{side}" for regime in REGIMES for side in SIDES)
RULE_OPERATORS = ("GTE", "LTE", "BETWEEN", "OUTSIDE")
RULE_KINDS = ("REQUIRED", "VETO", "FLIP")
LOW = -1e308
HIGH = 1e308

_META_PREFIX = "_builder_"


def new_rule(*, kind: str = "REQUIRED", evidence: str = "DI_SPREAD") -> dict:
    """Return one researcher-facing rule row with stable round-trip identity."""
    return {
        "id": uuid4().hex,
        "kind": kind,
        "evidence": evidence,
        "operator": "GTE",
        "value": 30.0 if evidence == "DI_SPREAD" else 0.0,
        "value2": 0.0,
        "regime": "ALL",
        "side": "ALL",
    }


def normalize_rule(rule: dict, *, expected_kind: str | None = None) -> dict:
    if not isinstance(rule, dict):
        raise ValueError("strategy rule must be an object")
    value = dict(rule)
    value.setdefault("id", uuid4().hex)
    value.setdefault("kind", expected_kind or "REQUIRED")
    value.setdefault("evidence", "DI_SPREAD")
    value.setdefault("operator", "GTE")
    value.setdefault("value", 0.0)
    value.setdefault("value2", 0.0)
    value.setdefault("regime", "ALL")
    value.setdefault("side", "ALL")
    if expected_kind is not None:
        value["kind"] = expected_kind
    value["kind"] = str(value["kind"]).upper()
    value["evidence"] = str(value["evidence"]).upper()
    value["operator"] = str(value["operator"]).upper()
    value["regime"] = str(value["regime"]).upper()
    value["side"] = str(value["side"]).upper()
    value["value"] = float(value["value"])
    value["value2"] = float(value["value2"])
    if value["kind"] not in RULE_KINDS:
        raise ValueError(f"unsupported strategy rule kind: {value['kind']}")
    if value["evidence"] not in RULE_INDICATORS:
        raise ValueError(f"unsupported strategy rule evidence: {value['evidence']}")
    if value["operator"] not in RULE_OPERATORS:
        raise ValueError(f"unsupported strategy rule operator: {value['operator']}")
    if value["regime"] not in ("ALL", *REGIMES):
        raise ValueError(f"unsupported strategy rule regime scope: {value['regime']}")
    if value["side"] not in ("ALL", *SIDES):
        raise ValueError(f"unsupported strategy rule side scope: {value['side']}")
    if value["operator"] in {"BETWEEN", "OUTSIDE"} and value["value"] > value["value2"]:
        raise ValueError("strategy rule lower value cannot exceed upper value")
    return value


def normalize_rules(rules, *, kind: str) -> tuple[dict, ...]:
    return tuple(normalize_rule(rule, expected_kind=kind) for rule in (rules or ()))


def _profile_scope(profile_key: str) -> tuple[str, str]:
    regime, source_side = profile_key.upper().split("_", 1)
    return regime, source_side


def effective_side(source_side: str, direction_mode: str) -> str:
    """Return the DI-selected side; permissions decide whether it may trade."""
    mode = str(direction_mode).upper()
    if mode != "DI":
        raise ValueError(f"unsupported direction mode: {direction_mode}")
    return source_side


def _applies(rule: dict, regime: str, side: str) -> bool:
    return rule["regime"] in ("ALL", regime) and rule["side"] in ("ALL", side)


def _range(rule: dict) -> tuple[float, float, str]:
    operator = rule["operator"]
    first, second = float(rule["value"]), float(rule["value2"])
    if operator == "GTE":
        return first, HIGH, "INSIDE"
    if operator == "LTE":
        return LOW, first, "INSIDE"
    if operator == "BETWEEN":
        return first, second, "INSIDE"
    if operator == "OUTSIDE":
        return first, second, "OUTSIDE"
    raise ValueError(f"unsupported strategy rule operator: {operator}")


def _native_rule(rule: dict, *, required: bool) -> dict:
    minimum, maximum, matching_condition = _range(rule)
    # A required rule rejects when its desired condition is false. A veto or
    # flip rule acts when its desired condition is true.
    condition = (
        "OUTSIDE" if matching_condition == "INSIDE" else "INSIDE"
    ) if required else matching_condition
    action = "FLIP" if rule["kind"] == "FLIP" else "REJECT"
    native = {
        "action": action,
        "indicator": rule["evidence"],
        "condition": condition,
        "minimum": minimum,
        "maximum": maximum,
        f"{_META_PREFIX}id": rule["id"],
        f"{_META_PREFIX}kind": rule["kind"],
        f"{_META_PREFIX}operator": rule["operator"],
        f"{_META_PREFIX}value": rule["value"],
        f"{_META_PREFIX}value2": rule["value2"],
        f"{_META_PREFIX}regime": rule["regime"],
        f"{_META_PREFIX}side": rule["side"],
    }
    return native


def compile_profiles(
    *,
    direction_mode: str,
    market_permissions,
    required_rules=(),
    veto_rules=(),
    flip_rules=(),
    rsi_period: int = 14,
    momentum_lookback_hours: int = 24,
    base_execution: ExecutionProfileConfig | None = None,
) -> tuple[dict[str, StrategyProfileConfig], dict[str, ExecutionProfileConfig]]:
    """Compile rule authoring into the exact mature six-input engine contract."""
    mode = str(direction_mode).upper()
    if mode not in DIRECTION_MODES:
        raise ValueError(f"unsupported direction mode: {direction_mode}")
    permissions = {str(item).upper() for item in market_permissions}
    unknown_permissions = sorted(permissions - set(MARKET_PERMISSIONS))
    if unknown_permissions:
        raise ValueError("unknown market permissions: " + ", ".join(unknown_permissions))
    required = normalize_rules(required_rules, kind="REQUIRED")
    veto = normalize_rules(veto_rules, kind="VETO")
    flips = normalize_rules(flip_rules, kind="FLIP")
    if int(rsi_period) <= 0 or int(momentum_lookback_hours) <= 0:
        raise ValueError("rule calculation periods must be positive")

    strategy_profiles: dict[str, StrategyProfileConfig] = {}
    execution_profiles: dict[str, ExecutionProfileConfig] = {}
    execution = base_execution or ExecutionProfileConfig()

    for key in PROFILE_KEYS:
        regime, source_side = _profile_scope(key)
        side = effective_side(source_side, mode)
        enabled = f"{regime}_{side}" in permissions
        native_rules = []
        for rule in required:
            if _applies(rule, regime, side):
                native_rules.append(_native_rule(rule, required=True))
        for rule in veto:
            if _applies(rule, regime, side):
                native_rules.append(_native_rule(rule, required=False))
        for rule in flips:
            if _applies(rule, regime, side):
                native_rules.append(_native_rule(rule, required=False))

        strategy_profiles[key] = StrategyProfileConfig(
            enabled=enabled,
            flip_direction=False,
            entry_rules=tuple(native_rules),
            flip_rule_match_mode="ANY",
            reject_rule_match_mode="ANY",
            rsi_period=int(rsi_period),
            momentum_lookback_hours=int(momentum_lookback_hours),
        )
        execution_profiles[key] = replace(execution)

    return strategy_profiles, execution_profiles


def _builder_rule(native_rule: dict) -> dict | None:
    if not isinstance(native_rule, dict) or f"{_META_PREFIX}id" not in native_rule:
        return None
    return normalize_rule({
        "id": native_rule[f"{_META_PREFIX}id"],
        "kind": native_rule.get(f"{_META_PREFIX}kind", "VETO"),
        "evidence": native_rule.get("indicator", "DI_SPREAD"),
        "operator": native_rule.get(f"{_META_PREFIX}operator", "BETWEEN"),
        "value": native_rule.get(f"{_META_PREFIX}value", native_rule.get("minimum", 0.0)),
        "value2": native_rule.get(f"{_META_PREFIX}value2", native_rule.get("maximum", 0.0)),
        "regime": native_rule.get(f"{_META_PREFIX}regime", "ALL"),
        "side": native_rule.get(f"{_META_PREFIX}side", "ALL"),
    })


def decompile_rules(strategy_profiles) -> dict[str, tuple[dict, ...]]:
    """Recover builder-authored rules from metadata embedded in compiled rules."""
    by_kind: dict[str, dict[str, dict]] = {kind: {} for kind in RULE_KINDS}
    for profile in strategy_profiles.values():
        for native in getattr(profile, "entry_rules", ()):
            rule = _builder_rule(native)
            if rule is None:
                continue
            by_kind[rule["kind"]][rule["id"]] = rule
    return {
        kind: tuple(deepcopy(list(items.values())))
        for kind, items in by_kind.items()
    }


def infer_direction_mode(strategy_profiles) -> str:
    """Return the only currently supported native direction strategy."""
    if any(bool(profile.flip_direction) for profile in strategy_profiles.values()):
        raise ValueError(
            "Static profile direction overrides are retired; use Direction Flip Rules instead"
        )
    return "DI"


def infer_market_permissions(strategy_profiles, direction_mode: str) -> tuple[str, ...]:
    # Validate the authored direction strategy even though DI preserves source side.
    effective_side("LONG", direction_mode)
    permissions = set()
    for key, profile in strategy_profiles.items():
        if not profile.enabled:
            continue
        regime, source_side = _profile_scope(key)
        permissions.add(f"{regime}_{source_side}")
    return tuple(item for item in MARKET_PERMISSIONS if item in permissions)


def common_execution_profile(execution_profiles) -> ExecutionProfileConfig:
    """Use the first profile as the base; builder-authored saves write all six equally."""
    for key in PROFILE_KEYS:
        if key in execution_profiles:
            return replace(execution_profiles[key])
    return ExecutionProfileConfig()
