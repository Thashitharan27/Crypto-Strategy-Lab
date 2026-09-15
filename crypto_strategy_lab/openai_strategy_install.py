"""Small compatibility installer for the first-class OpenAI signal strategy.

Keeping the integration here lets the new strategy use the existing mature
strategy/profile/runtime seams without duplicating the production engine.
"""
from __future__ import annotations

from dataclasses import replace
import importlib.abc
import importlib.machinery
import sys

from crypto_strategy_lab.ai_decision import OPENAI_DECISION_MODE, OpenAIDecisionMixin
from crypto_strategy_lab.ai_snapshot_enrichment import enrich_ai_snapshot


_INSTALLED = False
_LABEL = "AI Decision — OpenAI"
_LABEL_MODULES = {
    "crypto_strategy_lab.gui.rule_strategy_builder": "DIRECTION_LABELS",
    "crypto_strategy_lab.control_rule_workspace": "SIGNAL_STRATEGIES",
}


def _openai_marker_rule() -> dict:
    # A no-op reject marker: finite DI spread is inside this effectively
    # unbounded range, while a REJECT/OUTSIDE rule therefore never fires. The
    # marker is metadata only and exists so save/load can recover signal mode.
    return {
        "action": "REJECT",
        "indicator": "DI_SPREAD",
        "condition": "OUTSIDE",
        "minimum": -1e308,
        "maximum": 1e308,
        "_strategy_direction_mode": OPENAI_DECISION_MODE,
        "_strategy_builtin_rule": "OPENAI_DIRECTION_SIGNAL",
    }


def _patch_label_module(fullname: str, module) -> None:
    mapping_name = _LABEL_MODULES.get(fullname)
    if not mapping_name:
        return
    mapping = getattr(module, mapping_name, None)
    if isinstance(mapping, dict):
        mapping.setdefault(OPENAI_DECISION_MODE, _LABEL)


class _LabelPatchLoader(importlib.abc.Loader):
    def __init__(self, fullname: str, wrapped):
        self.fullname = fullname
        self.wrapped = wrapped

    def create_module(self, spec):
        creator = getattr(self.wrapped, "create_module", None)
        return creator(spec) if creator is not None else None

    def exec_module(self, module):
        self.wrapped.exec_module(module)
        _patch_label_module(self.fullname, module)


class _LabelPatchFinder(importlib.abc.MetaPathFinder):
    _openai_decision_label_finder = True

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in _LABEL_MODULES:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        if not isinstance(spec.loader, _LabelPatchLoader):
            spec.loader = _LabelPatchLoader(fullname, spec.loader)
        return spec


def _install_lazy_labels() -> None:
    for fullname in _LABEL_MODULES:
        module = sys.modules.get(fullname)
        if module is not None:
            _patch_label_module(fullname, module)
    if not any(
        getattr(finder, "_openai_decision_label_finder", False)
        for finder in sys.meta_path
    ):
        sys.meta_path.insert(0, _LabelPatchFinder())


def _install_strategy_authoring() -> None:
    from crypto_strategy_lab import strategy_rule_model as model

    if OPENAI_DECISION_MODE not in model.SIGNAL_STRATEGIES:
        model.SIGNAL_STRATEGIES = (*model.SIGNAL_STRATEGIES, OPENAI_DECISION_MODE)
    if OPENAI_DECISION_MODE not in model.DIRECTION_MODES:
        model.DIRECTION_MODES = (*model.DIRECTION_MODES, OPENAI_DECISION_MODE)

    if getattr(model.compile_profiles, "_openai_decision_wrapped", False):
        return
    original_compile = model.compile_profiles

    def compile_profiles_with_openai(*args, **kwargs):
        direction_mode = kwargs.get("direction_mode")
        if direction_mode is None and args:
            # compile_profiles is keyword-only today; retain a defensive fallback.
            direction_mode = args[0]
        profiles, execution_profiles = original_compile(*args, **kwargs)
        if str(direction_mode).upper() != OPENAI_DECISION_MODE:
            return profiles, execution_profiles
        marker = _openai_marker_rule()
        profiles = {
            key: replace(
                profile,
                entry_rules=(dict(marker), *tuple(profile.entry_rules)),
            )
            for key, profile in profiles.items()
        }
        return profiles, execution_profiles

    compile_profiles_with_openai._openai_decision_wrapped = True
    compile_profiles_with_openai.__name__ = original_compile.__name__
    compile_profiles_with_openai.__doc__ = original_compile.__doc__
    model.compile_profiles = compile_profiles_with_openai


def _install_runtime() -> None:
    from crypto_strategy_lab.engine import BacktestEngine

    if getattr(BacktestEngine, "_openai_decision_installed", False):
        return

    helper_names = (
        "_safe_array_value",
        "_ai_profile",
        "_ai_trade_contract",
        "_ai_sr_snapshot",
        "_ai_pressure_snapshot",
        "_ai_research_value",
        "_ai_futures_snapshot",
        "_ai_market_snapshot",
        "_ai_runtime_identity",
        "_ai_direction_decision",
    )
    for name in helper_names:
        setattr(BacktestEngine, name, getattr(OpenAIDecisionMixin, name))

    original_ai_market_snapshot = BacktestEngine._ai_market_snapshot
    original_infer = BacktestEngine._infer_signal_strategy_mode
    original_selected = BacktestEngine._selected_direction
    original_build_row = BacktestEngine._build_result_row

    def ai_market_snapshot(self, i):
        snapshot = original_ai_market_snapshot(self, i)
        return enrich_ai_snapshot(self, i, snapshot)

    def infer_signal_strategy_mode(self):
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                if str(rule.get("_strategy_direction_mode", "")).upper() == OPENAI_DECISION_MODE:
                    return OPENAI_DECISION_MODE
        return original_infer(self)

    def selected_direction(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == OPENAI_DECISION_MODE:
            return self._ai_direction_decision(i).selected_side
        return original_selected(self, i)

    def build_result_row(self, p, row_kind, positions):
        row = original_build_row(self, p, row_kind, positions)
        if getattr(self, "signal_strategy_mode", "DI") != OPENAI_DECISION_MODE:
            return row
        index = row.get("research_signal_index")
        try:
            decision = getattr(self, "_ai_decisions_by_index", {}).get(int(index))
        except (TypeError, ValueError):
            decision = None
        if decision is None:
            return row
        row.update(
            ai_long_confidence=decision.long_confidence,
            ai_short_confidence=decision.short_confidence,
            ai_selected_confidence=decision.selected_confidence,
            ai_decision_strength=decision.decision_strength,
            ai_conflict_level=decision.conflict_level,
            ai_key_long_factors=" | ".join(decision.key_long_factors),
            ai_key_short_factors=" | ".join(decision.key_short_factors),
            ai_decision_summary=decision.summary,
            ai_model=decision.model,
            ai_reasoning_effort=decision.reasoning_effort,
            ai_prompt_version=decision.prompt_version,
            ai_snapshot_hash=decision.snapshot_hash,
            ai_response_id=decision.response_id,
            ai_cache_hit=decision.cache_hit,
        )
        return row

    BacktestEngine._ai_market_snapshot = ai_market_snapshot
    BacktestEngine._infer_signal_strategy_mode = infer_signal_strategy_mode
    BacktestEngine._selected_direction = selected_direction
    BacktestEngine._build_result_row = build_result_row
    BacktestEngine._openai_decision_installed = True


def install_openai_decision_strategy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_strategy_authoring()
    _install_runtime()
    _install_lazy_labels()
    _INSTALLED = True
