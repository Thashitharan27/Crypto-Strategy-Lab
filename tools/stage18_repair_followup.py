from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "crypto_strategy_lab" / "engine.py"


def replace_exact(old: str, new: str, expected: int = 1) -> None:
    text = ENGINE.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual == expected:
        ENGINE.write_text(text.replace(old, new), encoding="utf-8")
        return
    if actual == 0 and text.count(new) == expected:
        return
    raise RuntimeError(
        f"engine.py: expected {expected} old or new matches, "
        f"found old={actual}, new={text.count(new)}"
    )


def main() -> None:
    # Legacy DI direction sizing is a sizing decision, not an R:R override.
    # Preserve its mirrored 1:1 levels. Strategy Profiles alone may override
    # reward:risk for the selected direction.
    replace_exact(
        '''        if self.config.enable_di_direction_sizing or self.config.enable_strategy_profiles:\n            applied_regime = profile_context[0] if active_profile is not None else "BASE"\n            base_reward_risk = self.config.tp_mult / stop_mult\n            long_reward_risk = base_reward_risk\n            short_reward_risk = base_reward_risk\n            if active_profile is not None:\n                if sizing_direction == "LONG": long_reward_risk = active_profile.reward_risk_ratio\n                elif sizing_direction == "SHORT": short_reward_risk = active_profile.reward_risk_ratio\n            long_target_distance = stop * long_reward_risk\n            short_target_distance = stop * short_reward_risk\n        elif self.config.enable_coin_flip_sizing:\n''',
        '''        if self.config.enable_strategy_profiles:\n            applied_regime = profile_context[0] if active_profile is not None else "BASE"\n            long_reward_risk = short_reward_risk = 1.0\n            if active_profile is not None:\n                if sizing_direction == "LONG": long_reward_risk = active_profile.reward_risk_ratio\n                elif sizing_direction == "SHORT": short_reward_risk = active_profile.reward_risk_ratio\n            long_target_distance = stop * long_reward_risk\n            short_target_distance = stop * short_reward_risk\n        elif self.config.enable_di_direction_sizing:\n            applied_regime = "BASE"\n            long_reward_risk = short_reward_risk = 1.0\n            long_target_distance = short_target_distance = stop\n        elif self.config.enable_coin_flip_sizing:\n''',
    )

    # Restore the historical audit note used by reports/tests. This is output
    # metadata only and does not alter entry eligibility or warm-up safeguards.
    replace_exact(
        '''            "indicator_warmup_complete":bool(np.isfinite(getattr(p,"adx",np.nan)) and np.isfinite(getattr(p,"bb_width",np.nan))),"adx_available_at_entry":bool(np.isfinite(getattr(p,"adx",np.nan))),"bb_width_available_at_entry":bool(np.isfinite(getattr(p,"bb_width",np.nan))),\n''',
        '''            "indicator_warmup_complete":bool(np.isfinite(getattr(p,"adx",np.nan)) and np.isfinite(getattr(p,"bb_width",np.nan))),"adx_available_at_entry":bool(np.isfinite(getattr(p,"adx",np.nan))),"bb_width_available_at_entry":bool(np.isfinite(getattr(p,"bb_width",np.nan))),"indicator_warmup_note":"Complete" if (np.isfinite(getattr(p,"adx",np.nan)) and np.isfinite(getattr(p,"bb_width",np.nan))) else "Indicator warm-up incomplete at entry; missing indicator values are expected until enough historical candles are available.",\n''',
    )

    # ANALYSIS_ONLY must not change the shared trade result values. The actual
    # S/R fields are already emitted by _pos_cols with *_sr_* names; avoid a
    # generic config flag that makes analysis-only rows differ from disabled.
    replace_exact(
        '''        row.update({"support_resistance_analysis_enabled":self.config.enable_support_resistance_analysis,"sr_filter_mode":self.config.sr_filter_mode})\n''',
        '''''',
    )


if __name__ == "__main__":
    main()
