from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != expected:
        raise RuntimeError(f"{path}: expected {expected} matches, found {actual}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    # These Stage 18 edits only enabled Strategy Profiles globally in tests
    # that exercise legacy-compatible engine behavior.  Restore the historical
    # tests instead of weakening profile classification warm-up safeguards.
    restore = [
        "tests/test_partial_stop_loss.py",
        "tests/test_partial_take_profit.py",
        "tests/test_random_entry.py",
        "tests/test_remaining_leg_timeout.py",
        "tests/test_support_resistance.py",
        "tests/test_trailing_profit.py",
    ]
    subprocess.run(
        ["git", "checkout", "origin/main", "--", *restore],
        cwd=ROOT,
        check=True,
    )

    # test_backtester contains genuine Stage 18 profile migrations for retired
    # one-off controls, but its shared helper must not force every historical
    # engine test through profile regime classification.
    replace_exact(
        "tests/test_backtester.py",
        '''    base.update(kw)\n    base["enable_strategy_profiles"] = True\n    base.setdefault("strategy_profiles", _profiles_for_legacy_config(base))\n    return BacktestConfig(**base)\n''',
        '''    base.update(kw)\n    if "strategy_profiles" in kw:\n        base.setdefault("enable_strategy_profiles", True)\n    return BacktestConfig(**base)\n''',
    )

    # Coin-flip / DI sizing tests should use the legacy-compatible execution
    # path by default.  Only the tests that explicitly verify profile R:R
    # enable profiles, and their tiny synthetic data gets a deterministic
    # SIDEWAYS classification context rather than bypassing production warm-up.
    replace_exact(
        "tests/test_coin_flip_sizing.py",
        '''    values.update(overrides)\n    sl = float(values.get("sl_mult", 2.0))\n    tp = float(values.get("tp_mult", 3.0))\n    reward_risk = 1.0 if values.get("enable_di_direction_sizing", False) else tp / sl\n    profile = StrategyProfile(enabled=True, stop_loss_multiple=sl, reward_risk_ratio=reward_risk)\n    values["enable_strategy_profiles"] = True\n    values.setdefault("strategy_profiles", {key: profile for key in PROFILE_KEYS})\n    return BacktestConfig(**values)\n''',
        '''    values.update(overrides)\n    return BacktestConfig(**values)\n''',
    )
    replace_exact(
        "tests/test_coin_flip_sizing.py",
        '''    engine.di_spread[:] = abs(plus - minus)\n    return engine\n''',
        '''    engine.di_spread[:] = abs(plus - minus)\n    engine.market_regime_values[:] = "SIDEWAYS"\n    return engine\n''',
    )
    replace_exact(
        "tests/test_coin_flip_sizing.py",
        '''            "strategy_profiles": direction_profiles(long_rr=2.0, short_rr=2.0),\n''',
        '''            "enable_strategy_profiles": True,\n            "strategy_profiles": direction_profiles(long_rr=2.0, short_rr=2.0),\n''',
    )
    replace_exact(
        "tests/test_coin_flip_sizing.py",
        '''            "strategy_profiles": direction_profiles(long_rr=2.0, short_rr=1.0),\n''',
        '''            "enable_strategy_profiles": True,\n            "strategy_profiles": direction_profiles(long_rr=2.0, short_rr=1.0),\n''',
        expected=2,
    )

    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
