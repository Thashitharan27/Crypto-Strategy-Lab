"""Research-only reproducible 50/50 LONG/SHORT direction source.

This module deliberately sits beside the daily-sequence experiment rather than
inside the normal strategy configuration. Coin-flip mode is active only when
both the Daily Win/Loss Sequence experiment and Coin Flip Direction are enabled.

The first trade of every research day always uses the normal strategy direction.
Only trade #2 and later for that same research day use the reproducible coin flip.
Trade #2 can additionally use a configurable risk multiplier (default 2x); trade
#3 onward returns to the profile's normal risk multiplier.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QSpinBox

from crypto_strategy_lab.strategy_profiles import profile_key


@dataclass(frozen=True)
class CoinFlipSettings:
    enabled: bool = False
    seed: int = 42
    second_trade_risk_multiplier: float = 2.0


_SETTINGS = CoinFlipSettings()
_PATCHED = False


def get_coin_flip_settings() -> CoinFlipSettings:
    return _SETTINGS


def set_coin_flip_settings(*, enabled: bool, seed: int, second_trade_risk_multiplier: float = 2.0) -> None:
    global _SETTINGS
    _SETTINGS = CoinFlipSettings(
        enabled=bool(enabled),
        seed=max(0, int(seed)),
        second_trade_risk_multiplier=max(0.01, float(second_trade_risk_multiplier)),
    )


def coin_flip_direction(index: int, seed: int) -> str:
    """Stable 50/50 direction for a candle index and seed."""
    payload = f"{int(seed)}:{int(index)}".encode("utf-8")
    value = hashlib.blake2b(payload, digest_size=8).digest()[0]
    return "LONG" if value & 1 else "SHORT"


def coin_flip_applies_to_trade_number(trade_number: int) -> bool:
    """The first research trade is normal; only trade #2 onward is random."""
    return int(trade_number) >= 2


def risk_multiplier_for_trade_number(trade_number: int, second_trade_multiplier: float = 2.0) -> float:
    """Only trade #2 receives the research risk boost."""
    return float(second_trade_multiplier) if int(trade_number) == 2 else 1.0


def _coin_mode(engine) -> bool:
    coin = getattr(engine, "_research_coin_flip_settings", CoinFlipSettings())
    daily = getattr(engine, "_research_daily_settings", None)
    return bool(coin.enabled and daily is not None and daily.enabled)


def _current_trade_number(engine) -> int:
    """Return the pending research trade number for its entry day."""
    day = getattr(engine, "_research_daily_pending_day", None)
    if day is None:
        return 1
    ledger = getattr(engine, "_research_daily_ledger", {})
    state = ledger.get(day)
    existing_entries = int(state.get("entries", 0)) if state is not None else 0
    return existing_entries + 1


def _coin_for_current_entry(engine) -> bool:
    """Return True only when the pending research entry is trade #2 or later."""
    return bool(_coin_mode(engine) and coin_flip_applies_to_trade_number(_current_trade_number(engine)))


def install_coin_flip_support() -> None:
    """Patch direction/profile selection once; normal runs remain untouched."""
    global _PATCHED
    if _PATCHED:
        return

    from crypto_strategy_lab.engine import BacktestEngine

    original_init = BacktestEngine.__init__
    original_selected_direction = BacktestEngine._selected_direction
    original_profile_context = BacktestEngine._profile_context
    original_open_pair = BacktestEngine._open_pair
    original_build_result_row = BacktestEngine._build_result_row
    original_results_frame = BacktestEngine.results_frame

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._research_coin_flip_settings = replace(get_coin_flip_settings())

    def patched_selected_direction(self, i):
        if _coin_for_current_entry(self):
            return coin_flip_direction(i, self._research_coin_flip_settings.seed)
        return original_selected_direction(self, i)

    def patched_profile_context(self, i):
        if not _coin_for_current_entry(self):
            return original_profile_context(self, i)

        regime = self._regime_at(i)
        if regime is None:
            return None
        direction = coin_flip_direction(i, self._research_coin_flip_settings.seed)
        key = profile_key(regime, direction)
        profile = self.config.strategy_profiles[key]

        # Coin flip must remain the final direction on trade #2 onward. Preserve
        # REJECT filters and all exit settings, but disable profile FLIP.
        reject_only = tuple(
            rule for rule in profile.entry_rules
            if str(rule.get("action", "")).upper() != "FLIP"
        )
        trade_number = _current_trade_number(self)
        research_risk_multiplier = risk_multiplier_for_trade_number(
            trade_number,
            self._research_coin_flip_settings.second_trade_risk_multiplier,
        )
        profile = replace(
            profile,
            flip_direction=False,
            entry_rules=reject_only,
            risk_multiplier=profile.risk_multiplier * research_risk_multiplier,
        )
        return regime, direction, key, profile

    def patched_open_pair(self, *args, **kwargs):
        before = len(self.active_pairs)
        result = original_open_pair(self, *args, **kwargs)
        if _coin_mode(self) and len(self.active_pairs) > before:
            pair = self.active_pairs[-1]
            trade_number = int(getattr(pair, "research_daily_sequence_trade_number", 1) or 1)
            use_coin = coin_flip_applies_to_trade_number(trade_number)
            applied_research_risk_multiplier = risk_multiplier_for_trade_number(
                trade_number,
                self._research_coin_flip_settings.second_trade_risk_multiplier,
            )

            # _open_pair's first positional argument is the execution candle.
            i = int(args[0]) if args else int(kwargs.get("i", getattr(self, "current_index", 0)))
            schedule = args[3] if len(args) > 3 else kwargs.get("schedule")
            indicator_i = int(schedule.get("indicator_index", i)) if schedule else i
            plus = float(self.plus_di_values[indicator_i])
            minus = float(self.minus_di_values[indicator_i])
            strategy_direction = None
            if plus == plus and minus == minus and plus != minus:
                strategy_direction = "LONG" if plus > minus else "SHORT"

            pair.research_original_di_direction = strategy_direction
            pair.research_coin_flip_seed = self._research_coin_flip_settings.seed
            pair.research_risk_multiplier_applied = applied_research_risk_multiplier
            pair.research_second_trade_risk_multiplier = self._research_coin_flip_settings.second_trade_risk_multiplier
            if use_coin:
                pair.research_entry_direction_source = "COIN_FLIP_50_50_AFTER_FIRST"
                pair.research_coin_flip_direction = coin_flip_direction(
                    indicator_i, self._research_coin_flip_settings.seed
                )
            else:
                pair.research_entry_direction_source = "NORMAL_STRATEGY_FIRST_TRADE"
                pair.research_coin_flip_direction = None
        return result

    def patched_build_result_row(self, pair, row_kind, positions):
        row = original_build_result_row(self, pair, row_kind, positions)
        coin = self._research_coin_flip_settings
        row.update({
            "research_entry_direction_source": getattr(
                pair,
                "research_entry_direction_source",
                "NORMAL_STRATEGY",
            ),
            "research_coin_flip_direction": getattr(pair, "research_coin_flip_direction", None),
            "research_coin_flip_seed": getattr(pair, "research_coin_flip_seed", coin.seed if _coin_mode(self) else None),
            "research_original_di_direction": getattr(pair, "research_original_di_direction", None),
            "research_risk_multiplier_applied": getattr(pair, "research_risk_multiplier_applied", 1.0 if _coin_mode(self) else None),
            "research_second_trade_risk_multiplier": getattr(
                pair,
                "research_second_trade_risk_multiplier",
                coin.second_trade_risk_multiplier if _coin_mode(self) else None,
            ),
        })
        return row

    def patched_results_frame(self):
        frame = original_results_frame(self)
        coin = self._research_coin_flip_settings
        frame.attrs["research_coin_flip"] = {
            "enabled": bool(coin.enabled and getattr(self, "_research_daily_settings", None) and self._research_daily_settings.enabled),
            "seed": coin.seed,
            "direction_probability": "Trade #1 normal strategy; Trade #2+ 50% LONG / 50% SHORT",
            "first_trade_normal": True,
            "second_trade_risk_multiplier": coin.second_trade_risk_multiplier,
            "second_trade_only_risk_boost": True,
        }
        return frame

    BacktestEngine.__init__ = patched_init
    BacktestEngine._selected_direction = patched_selected_direction
    BacktestEngine._profile_context = patched_profile_context
    BacktestEngine._open_pair = patched_open_pair
    BacktestEngine._build_result_row = patched_build_result_row
    BacktestEngine.results_frame = patched_results_frame
    _PATCHED = True


def attach_coin_flip_controls(research_tab) -> QGroupBox:
    """Append coin-flip controls to the existing Research tab."""
    group = QGroupBox("Research Entry Direction")
    form = QFormLayout(group)

    mode = QComboBox()
    mode.addItem("Normal strategy direction", "NORMAL_STRATEGY")
    mode.addItem("Normal first trade, then coin flip 50/50", "COIN_FLIP_50_50")
    seed = QSpinBox()
    seed.setRange(0, 2_147_483_647)
    seed.setValue(42)
    seed.setToolTip("Same seed + same dataset/config = same coin-flip directions from trade #2 onward")
    second_risk = QDoubleSpinBox()
    second_risk.setRange(0.01, 20.0)
    second_risk.setDecimals(2)
    second_risk.setSingleStep(0.25)
    second_risk.setValue(2.0)
    second_risk.setSuffix("x")
    second_risk.setToolTip("Risk multiplier for Trade #2 only; Trade #1 and Trade #3+ remain at normal profile risk")
    summary = QLabel()
    summary.setWordWrap(True)

    form.addRow("Direction source", mode)
    form.addRow("Random seed", seed)
    form.addRow("Trade #2 risk multiplier", second_risk)
    form.addRow("", summary)

    layout = research_tab.layout()
    insert_at = max(0, layout.count() - 1)
    layout.insertWidget(insert_at, group)

    def apply():
        coin_enabled = mode.currentData() == "COIN_FLIP_50_50"
        daily_enabled = bool(research_tab.enabled.isChecked())
        seed.setEnabled(coin_enabled)
        second_risk.setEnabled(coin_enabled)
        set_coin_flip_settings(
            enabled=coin_enabled,
            seed=seed.value(),
            second_trade_risk_multiplier=second_risk.value(),
        )
        if coin_enabled and daily_enabled:
            summary.setText(
                f"Trade #1 uses the normal strategy direction and normal risk. Trade #2 uses a "
                f"reproducible 50/50 LONG/SHORT coin flip at {second_risk.value():.2f}x normal risk. "
                "Trade #3 onward continues with coin-flip direction but returns to normal risk. "
                "Profile FLIP rules are ignored for coin-flip trades; REJECT rules and exit mechanics remain active."
            )
        elif coin_enabled:
            summary.setText(
                f"Selected: first trade normal; Trade #2 coin flip at {second_risk.value():.2f}x risk; "
                "Trade #3+ coin flip at normal risk. It becomes active only when Daily Win/Loss Sequence is enabled."
            )
        else:
            summary.setText("Use the normal strategy direction and normal risk for every trade.")

    mode.currentIndexChanged.connect(apply)
    seed.valueChanged.connect(apply)
    second_risk.valueChanged.connect(apply)
    research_tab.enabled.toggled.connect(apply)
    apply()

    research_tab.research_direction_mode = mode
    research_tab.research_coin_flip_seed = seed
    research_tab.research_second_trade_risk_multiplier = second_risk
    return group
