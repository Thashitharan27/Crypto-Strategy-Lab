"""Temporary Research-tab experiment: daily win/loss sequence entry gating.

The experiment is intentionally isolated from the normal strategy/config contract.
When enabled for a run, new entries are allowed until either wins lead losses by
``win_lead`` (default 1) or losses lead wins by ``loss_lead`` (default 5).

A trade belongs permanently to the configured research calendar day containing
its ENTRY timestamp. Its eventual outcome updates that same day's ledger even if
it exits after midnight. This avoids cross-midnight exits resetting or mutating
another day's counters.
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


def _new_day_state() -> dict:
    return {
        "wins": 0,
        "losses": 0,
        "entries": 0,
        "completed": 0,
        "stop_reason": None,
    }


def _ledger_for(engine, day: date) -> dict:
    return engine._research_daily_ledger.setdefault(day, _new_day_state())


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
        self._research_daily_ledger = {}
        self._research_daily_pending_day = None
        self._research_daily_entries_blocked = 0

    def patched_collect(self, force=False):
        before = len(self.completed_pairs)
        result = original_collect(self, force=force)
        settings = self._research_daily_settings
        if not settings.enabled:
            return result

        for pair in self.completed_pairs[before:]:
            # The research day is fixed at ENTRY. Never derive bookkeeping day
            # from exit_time, because trades can cross midnight.
            day_text = getattr(pair, "research_daily_sequence_day", None)
            if day_text:
                day = date.fromisoformat(str(day_text))
            else:
                day = _day_for(pair.strategy_entry_time, settings.timezone)
                pair.research_daily_sequence_day = str(day)

            state = _ledger_for(self, day)
            pnl = _pair_net_pnl(pair)
            if pnl > 1e-12:
                outcome = "W"
                state["wins"] += 1
            elif pnl < -1e-12:
                outcome = "L"
                state["losses"] += 1
            else:
                outcome = "N"
            state["completed"] += 1

            reason = stop_reason(
                state["wins"],
                state["losses"],
                settings.win_lead,
                settings.loss_lead,
            )
            state["stop_reason"] = reason

            pair.research_daily_sequence_outcome = outcome
            pair.research_daily_sequence_exit_day = str(_day_for(_pair_exit_time(pair), settings.timezone))
            pair.research_daily_sequence_wins_after = state["wins"]
            pair.research_daily_sequence_losses_after = state["losses"]
            pair.research_daily_sequence_stop_reason_after = reason
        return result

    def patched_entry_decision(self, i, active_at_candle_start=False):
        decision = original_entry_decision(self, i, active_at_candle_start)
        settings = self._research_daily_settings
        self._research_daily_pending_day = None
        if decision is None or not settings.enabled:
            return decision

        entry_time = decision.get("actual_entry_timestamp") or self._execution_time(i)
        day = _day_for(entry_time, settings.timezone)
        state = _ledger_for(self, day)
        reason = stop_reason(
            state["wins"],
            state["losses"],
            settings.win_lead,
            settings.loss_lead,
        )
        state["stop_reason"] = reason
        if reason is not None:
            self._research_daily_entries_blocked += 1
            return None

        # Preserve the exact day used by the entry gate so _open_pair cannot be
        # affected by any unrelated trade completion between these calls.
        self._research_daily_pending_day = day
        return decision

    def patched_open_pair(self, *args, **kwargs):
        settings = self._research_daily_settings
        before = len(self.active_pairs)
        result = original_open_pair(self, *args, **kwargs)
        if settings.enabled and len(self.active_pairs) > before:
            pair = self.active_pairs[-1]
            day = self._research_daily_pending_day
            if day is None:
                day = _day_for(pair.strategy_entry_time, settings.timezone)
            state = _ledger_for(self, day)

            pair.research_daily_sequence_enabled = True
            pair.research_daily_sequence_day = str(day)
            pair.research_daily_sequence_wins_before = state["wins"]
            pair.research_daily_sequence_losses_before = state["losses"]
            state["entries"] += 1
            pair.research_daily_sequence_trade_number = state["entries"]
            pair.research_daily_sequence_win_lead = settings.win_lead
            pair.research_daily_sequence_loss_lead = settings.loss_lead
            pair.research_daily_sequence_timezone = settings.timezone
        self._research_daily_pending_day = None
        return result

    def patched_build_result_row(self, pair, row_kind, positions):
        row = original_build_result_row(self, pair, row_kind, positions)
        settings = self._research_daily_settings
        row.update({
            "research_daily_sequence_enabled": bool(settings.enabled),
            "research_daily_sequence_day": getattr(pair, "research_daily_sequence_day", None),
            "research_daily_sequence_exit_day": getattr(pair, "research_daily_sequence_exit_day", None),
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
            "research_days": len(getattr(self, "_research_daily_ledger", {})),
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
            "Each trade belongs to the research calendar day containing its ENTRY timestamp. "
            "Positive net PnL after fees = W, negative = L, exactly zero = neutral. "
            "A trade that exits after midnight still updates its original entry day's counters. "
            "When a stop boundary is reached, later qualifying entries for that research day are ignored."
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
            f"or L >= W + {self.loss_lead.value()}. Then stop entries for that {timezone} research day."
        )


def attach_research_tab(window) -> ResearchTab:
    tab = ResearchTab(window)
    window.research_tab = tab
    window.tabs.addTab(tab, "Research")
    return tab
