"""Research-only reproducible 50/50 LONG/SHORT direction source.

This module deliberately sits beside the daily-sequence experiment rather than
inside the normal strategy configuration. Coin-flip mode is active only when
both the Daily Win/Loss Sequence experiment and Coin Flip Direction are enabled.

The first trade of every research day always uses the normal strategy direction.
Only trade #2 and later for that same research day use the reproducible coin flip.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QSpinBox

from crypto_strategy_lab.strategy_profiles import profile_key


@dataclass(frozen=True)
class CoinFlipSettings:
    enabled: bool = False
    seed: int = 42


_SETTINGS = CoinFlipSettings()
_PATCHED = False


def get_coin_flip_settings() -> CoinFlipSettings:
    return _SETTINGS


def set_coin_flip_settings(*, enabled: bool, seed: int) -> None:
    global _SETTINGS
    _SETTINGS = CoinFlipSettings(enabled=bool(enabled), seed=max(0, int(seed)))


def coin_flip_direction(index: int, seed: int) -> str:
    """Stable 50/50 direction for a candle index and seed."""
    payload = f"{int(seed)}:{int(index)}".encode("utf-8")
    value = hashlib.blake2b(payload, digest_size=8).digest()[0]
    return "LONG" if value & 1 else "SHORT"


def coin_flip_applies_to_trade_number(trade_number: int) -> bool:
    """The first research trade is normal; only trade #2 onward is random."""
    return int(trade_number) >= 2


def _coin_mode(engine) -> bool:
    coin = getattr(engine, "_research_coin_flip_settings", CoinFlipSettings())
    daily = getattr(engine, "_research_daily_settings", None)
    return bool(coin.enabled and daily is not None and daily.enabled)


def _coin_for_current_entry(engine) -> bool:
    """Return True only when the pending research entry is trade #2 or later.

    The daily-sequence hook sets ``_research_daily_pending_day`` before entry
    filters/profile selection run. Its ledger entry counter therefore tells us
    whether the candidate is the first trade of that research day without
    changing any normal strategy state.
    """
    if not _coin_mode(engine):
        return False
    day = getattr(engine, "_research_daily_pending_day", None)
    if day is None:
        return False
    ledger = getattr(engine, "_research_daily_ledger", {})
    state = ledger.get(day)
    existing_entries = int(state.get("entries", 0)) if state is not None else 0
    return existing_entries >= 1


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
        # REJECT filters and all risk/exit settings, but disable profile FLIP.
        reject_only = tuple(
            rule for rule in profile.entry_rules
            if str(rule.get("action", "")).upper() != "FLIP"
        )
        profile = replace(profile, flip_direction=False, entry_rules=reject_only)
        return regime, direction, key, profile

    def patched_open_pair(self, *args, **kwargs):
        before = len(self.active_pairs)
        result = original_open_pair(self, *args, **kwargs)
        if _coin_mode(self) and len(self.active_pairs) > before:
            pair = self.active_pairs[-1]
            trade_number = int(getattr(pair, "research_daily_sequence_trade_number", 1) or 1)
            use_coin = coin_flip_applies_to_trade_number(trade_number)

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
    summary = QLabel()
    summary.setWordWrap(True)

    form.addRow("Direction source", mode)
    form.addRow("Random seed", seed)
    form.addRow("", summary)

    layout = research_tab.layout()
    insert_at = max(0, layout.count() - 1)
    layout.insertWidget(insert_at, group)

    def apply():
        coin_enabled = mode.currentData() == "COIN_FLIP_50_50"
        daily_enabled = bool(research_tab.enabled.isChecked())
        seed.setEnabled(coin_enabled)
        set_coin_flip_settings(enabled=coin_enabled, seed=seed.value())
        if coin_enabled and daily_enabled:
            summary.setText(
                "Trade #1 of every research day uses the normal strategy direction. "
                "Only Trade #2 onward uses a reproducible 50/50 LONG/SHORT coin flip. "
                "For coin-flip trades, profile FLIP rules are ignored while profile REJECT rules, "
                "risk sizing, SL/TP and the daily W/L stopping rules remain active."
            )
        elif coin_enabled:
            summary.setText(
                "Selected: first trade normal, Trade #2 onward coin flip. "
                "It becomes active only when Daily Win/Loss Sequence is enabled."
            )
        else:
            summary.setText("Use the normal strategy direction for every trade.")

    mode.currentIndexChanged.connect(apply)
    seed.valueChanged.connect(apply)
    research_tab.enabled.toggled.connect(apply)
    apply()

    research_tab.research_direction_mode = mode
    research_tab.research_coin_flip_seed = seed
    return group
