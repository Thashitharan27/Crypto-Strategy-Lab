"""Temporary Research-tab experiment: daily win/loss sequence entry gating.

The experiment is intentionally isolated from the normal strategy/config contract.
When enabled for a run, new entries are allowed until either wins lead losses by
``win_lead`` (default 1) or losses lead wins by ``loss_lead`` (default 5).
Counters reset at the configured calendar-day boundary. Pair net PnL including
fees decides W/L; exactly zero is neutral and does not change either counter.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class DailySequenceSettings:
    enabled: bool = False
    win_lead: int = 1
    loss_lead: int = 5
    timezone: str = "UTC"


_SETTINGS = DailySequenceSettings()
_PATCHED = False


def get_settings() -> DailySequenceSettings:
    return _SETTINGS


def set_settings(*, enabled: bool, win_lead: int, loss_lead: int, timezone: str) -> None:
    global _SETTINGS
    timezone = str(timezone).strip() or "UTC"
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        timezone = "UTC"
    _SETTINGS = DailySequenceSettings(
        enabled=bool(enabled),
        win_lead=max(1, int(win_lead)),
        loss_lead=max(1, int(loss_lead)),
        timezone=timezone,
    )


def stop_reason(wins: int, losses: int, win_lead: int = 1, loss_lead: int = 5) -> str | None:
    """Return the active daily stop boundary, if any."""
    if wins >= losses + win_lead:
        return "WIN_LEAD_REACHED"
    if losses >= wins + loss_lead:
        return "LOSS_LEAD_REACHED"
    return None


def _day_for(timestamp, timezone: str) -> date:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(ZoneInfo(timezone)).date()


def _reset_day(engine, day: date) -> None:
    engine._research_daily_day = day
    engine._research_daily_wins = 0
    engine._research_daily_losses = 0
    engine._research_daily_stop_reason = None


def _ensure_day(engine, day: date) -> None:
    if getattr(engine, "_research_daily_day", None) != day:
        _reset_day(engine, day)


def _pair_net_pnl(pair) -> float:
    return float(sum(float(getattr(pos, "net_pnl", 0.0) or 0.0) for pos in pair.positions()))


def _pair_exit_time(pair):
    times = [pd.Timestamp(pos.exit_time) for pos in pair.positions() if pos.exit_time is not None]
    return max(times) if times else pd.Timestamp(pair.strategy_entry_time)


def install_research_support() -> None:
    """Patch BacktestEngine once, keeping all research behavior opt-in."""
    global _PATCHED
    if _PATCHED:
        return

    from crypto_strategy_lab.engine import BacktestEngine

    original_init = BacktestEngine.__init__
    original_collect = BacktestEngine._collect_closed_pairs
    original_entry_decision = BacktestEngine._entry_decision
    original_open_pair = BacktestEngine._open_pair
    original_build_result_row = BacktestEngine._build_result_row
    original_results_frame = BacktestEngine.results_frame

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._research_daily_settings = replace(get_settings())
        self._research_daily_day = None
        self._research_daily_wins = 0
        self._research_daily_losses = 0
        self._research_daily_stop_reason = None
        self._research_daily_entries_blocked = 0

    def patched_collect(self, force=False):
        before = len(self.completed_pairs)
        result = original_collect(self, force=force)
        settings = self._research_daily_settings
        if not settings.enabled:
            return result

        for pair in self.completed_pairs[before:]:
            exit_time = _pair_exit_time(pair)
            day = _day_for(exit_time, settings.timezone)
            _ensure_day(self, day)

            pnl = _pair_net_pnl(pair)
            if pnl > 1e-12:
                outcome = "W"
                self._research_daily_wins += 1
            elif pnl < -1e-12:
                outcome = "L"
                self._research_daily_losses += 1
            else:
                outcome = "N"

            reason = stop_reason(
                self._research_daily_wins,
                self._research_daily_losses,
                settings.win_lead,
                settings.loss_lead,
            )
            self._research_daily_stop_reason = reason
            pair.research_daily_sequence_outcome = outcome
            pair.research_daily_sequence_exit_day = str(day)
            pair.research_daily_sequence_wins_after = self._research_daily_wins
            pair.research_daily_sequence_losses_after = self._research_daily_losses
            pair.research_daily_sequence_stop_reason_after = reason
        return result

    def patched_entry_decision(self, i, active_at_candle_start=False):
        decision = original_entry_decision(self, i, active_at_candle_start)
        settings = self._research_daily_settings
        if decision is None or not settings.enabled:
            return decision

        entry_time = decision.get("actual_entry_timestamp") or self._execution_time(i)
        day = _day_for(entry_time, settings.timezone)
        _ensure_day(self, day)
        reason = stop_reason(
            self._research_daily_wins,
            self._research_daily_losses,
            settings.win_lead,
            settings.loss_lead,
        )
        self._research_daily_stop_reason = reason
        if reason is not None:
            self._research_daily_entries_blocked += 1
            return None
        return decision

    def patched_open_pair(self, *args, **kwargs):
        settings = self._research_daily_settings
        before = len(self.active_pairs)
        result = original_open_pair(self, *args, **kwargs)
        if settings.enabled and len(self.active_pairs) > before:
            pair = self.active_pairs[-1]
            day = getattr(self, "_research_daily_day", None)
            pair.research_daily_sequence_enabled = True
            pair.research_daily_sequence_day = str(day) if day is not None else None
            pair.research_daily_sequence_wins_before = self._research_daily_wins
            pair.research_daily_sequence_losses_before = self._research_daily_losses
            pair.research_daily_sequence_trade_number = self._research_daily_wins + self._research_daily_losses + 1
            pair.research_daily_sequence_win_lead = settings.win_lead
            pair.research_daily_sequence_loss_lead = settings.loss_lead
            pair.research_daily_sequence_timezone = settings.timezone
        return result

    def patched_build_result_row(self, pair, row_kind, positions):
        row = original_build_result_row(self, pair, row_kind, positions)
        settings = self._research_daily_settings
        row.update({
            "research_daily_sequence_enabled": bool(settings.enabled),
            "research_daily_sequence_day": getattr(pair, "research_daily_sequence_day", None),
            "research_daily_sequence_trade_number": getattr(pair, "research_daily_sequence_trade_number", None),
            "research_daily_sequence_wins_before": getattr(pair, "research_daily_sequence_wins_before", None),
            "research_daily_sequence_losses_before": getattr(pair, "research_daily_sequence_losses_before", None),
            "research_daily_sequence_outcome": getattr(pair, "research_daily_sequence_outcome", None),
            "research_daily_sequence_wins_after": getattr(pair, "research_daily_sequence_wins_after", None),
            "research_daily_sequence_losses_after": getattr(pair, "research_daily_sequence_losses_after", None),
            "research_daily_sequence_stop_reason_after": getattr(pair, "research_daily_sequence_stop_reason_after", None),
            "research_daily_sequence_win_lead": settings.win_lead if settings.enabled else None,
            "research_daily_sequence_loss_lead": settings.loss_lead if settings.enabled else None,
            "research_daily_sequence_timezone": settings.timezone if settings.enabled else None,
        })
        return row

    def patched_results_frame(self):
        frame = original_results_frame(self)
        settings = self._research_daily_settings
        frame.attrs["research_daily_sequence"] = {
            "enabled": bool(settings.enabled),
            "win_lead": settings.win_lead,
            "loss_lead": settings.loss_lead,
            "timezone": settings.timezone,
            "entries_blocked_after_daily_stop": int(getattr(self, "_research_daily_entries_blocked", 0)),
        }
        return frame

    BacktestEngine.__init__ = patched_init
    BacktestEngine._collect_closed_pairs = patched_collect
    BacktestEngine._entry_decision = patched_entry_decision
    BacktestEngine._open_pair = patched_open_pair
    BacktestEngine._build_result_row = patched_build_result_row
    BacktestEngine.results_frame = patched_results_frame
    _PATCHED = True


class ResearchTab(QWidget):
    """Small, intentionally separate home for temporary/unconventional tests."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)

        intro = QLabel(
            "Temporary experiments live here so they do not become part of the normal strategy controls. "
            "Settings are snapshotted when a backtest engine starts and affect only that run."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        group = QGroupBox("Daily Win/Loss Sequence")
        form = QFormLayout(group)
        self.enabled = QCheckBox("Enable this research experiment")
        self.win_lead = QSpinBox(); self.win_lead.setRange(1, 20); self.win_lead.setValue(1)
        self.loss_lead = QSpinBox(); self.loss_lead.setRange(1, 20); self.loss_lead.setValue(5)
        self.timezone = QLineEdit("UTC")
        self.rule_summary = QLabel(); self.rule_summary.setWordWrap(True)
        note = QLabel(
            "Outcome is based on the completed trade pair's net PnL after fees. "
            "Positive = W, negative = L, exactly zero = neutral. Counters reset on each calendar day. "
            "When a stop boundary is reached, later qualifying entries that day are ignored."
        )
        note.setWordWrap(True)

        form.addRow("", self.enabled)
        form.addRow("Stop when W = L +", self.win_lead)
        form.addRow("Stop when L = W +", self.loss_lead)
        form.addRow("Day boundary timezone", self.timezone)
        form.addRow("Rule", self.rule_summary)
        form.addRow("", note)
        outer.addWidget(group)
        outer.addStretch(1)

        self.enabled.toggled.connect(self._apply)
        self.win_lead.valueChanged.connect(self._apply)
        self.loss_lead.valueChanged.connect(self._apply)
        self.timezone.editingFinished.connect(self._apply)
        self._apply()

    def _apply(self):
        timezone = self.timezone.text().strip() or "UTC"
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            timezone = "UTC"
            self.timezone.setText(timezone)
        set_settings(
            enabled=self.enabled.isChecked(),
            win_lead=self.win_lead.value(),
            loss_lead=self.loss_lead.value(),
            timezone=timezone,
        )
        self.rule_summary.setText(
            f"Keep taking normal qualifying trades until W >= L + {self.win_lead.value()} "
            f"or L >= W + {self.loss_lead.value()}. Then stop entries until the next {timezone} day."
        )


def attach_research_tab(window) -> ResearchTab:
    tab = ResearchTab(window)
    window.research_tab = tab
    window.tabs.addTab(tab, "Research")
    return tab
