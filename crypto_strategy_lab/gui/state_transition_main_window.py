"""Top-level GUI composition for automatic state-transition research reports.

This layer preserves the existing enhanced/SR-aware main window and only swaps
its single-backtest worker for the research-reporting wrapper. It also exposes a
visible Summary report button for the generated state-transition folder.
"""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from crypto_strategy_lab.gui import main_window as base_main_window_module
from crypto_strategy_lab.gui.state_transition_worker import StateTransitionBacktestWorker

# BaseMainWindow.run_backtest resolves BacktestWorker from its defining module at
# runtime. Replacing that module global preserves every enhanced/SR GUI layer
# while adding the post-run research export.
base_main_window_module.BacktestWorker = StateTransitionBacktestWorker
base_main_window_module.REPORT_TARGETS["state"] = "state_transition_research"

from crypto_strategy_lab.gui.sr_dynamic_tp_main_window import MainWindow as SRDynamicTPMainWindow


class MainWindow(SRDynamicTPMainWindow):
    """Existing full GUI plus a visible State Research report shortcut."""

    def _build_summary(self):
        super()._build_summary()
        if "state" in self.report_buttons:
            return
        button = QPushButton("Open State Research")
        button.setEnabled(False)
        button.clicked.connect(lambda _checked=False: self._open_report("state"))
        self.report_buttons["state"] = button

        # The existing six report buttons occupy two rows of three. Put the
        # research shortcut on the next row without restructuring the base UI.
        reports_layout = self.report_buttons["output"].parentWidget().layout()
        reports_layout.addWidget(button, 2, 0)
