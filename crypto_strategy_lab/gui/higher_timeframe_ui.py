"""UI helpers for downloaded Binance higher-timeframe voting data."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from .binance_dialog import BinanceDownloadDialog


class BinanceHigherTimeframeCombo(QComboBox):
    """Combo box that preserves the old QSpinBox value()/setValue() API."""

    OPTIONS = (("1 hour (1h)", 1, "1h"), ("4 hours (4h)", 4, "4h"), ("1 day (1d)", 24, "1d"))

    def __init__(self, parent=None):
        super().__init__(parent)
        for label, hours, interval in self.OPTIONS:
            self.addItem(label, (hours, interval))

    def value(self) -> int:
        data = self.currentData()
        return int(data[0]) if data else 4

    def interval(self) -> str:
        data = self.currentData()
        return str(data[1]) if data else "4h"

    def setValue(self, hours: int) -> None:
        hours = int(hours)
        for index in range(self.count()):
            if int(self.itemData(index)[0]) == hours:
                self.setCurrentIndex(index)
                return
        # Backward compatibility: old configs may contain another hour value.
        # Keep it visible, but mark it unsupported so the user can switch to a
        # real Binance interval before running/downloading.
        self.addItem(f"{hours} hours (legacy / unsupported by downloader)", (hours, f"{hours}h"))
        self.setCurrentIndex(self.count() - 1)


def install_higher_timeframe_ui(MainWindow) -> None:
    """Add a Binance HTF selector, path preview, and dedicated download button."""
    if getattr(MainWindow, "_binance_htf_ui_patch", False):
        return

    original_init = MainWindow.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        old_hours = self.direction_vote_htf_hours
        old_value = int(old_hours.value())
        layout = self.direction_voting_box.layout()
        label = layout.labelForField(old_hours)
        if label is not None:
            label.hide()
        old_hours.hide()

        combo = BinanceHigherTimeframeCombo(self)
        combo.setValue(old_value)
        self.direction_vote_htf_hours = combo
        layout.addRow("Higher Timeframe", combo)

        self.direction_vote_htf_dataset = QLabel(self)
        self.direction_vote_htf_dataset.setWordWrap(True)
        layout.addRow("HTF Dataset", self.direction_vote_htf_dataset)

        self.direction_vote_htf_download = QPushButton("Download / Update HTF Dataset", self)
        layout.addRow("", self.direction_vote_htf_download)
        self.htf_download_dialog = None

        def update_path(*_):
            symbol = self.market_symbol.currentText().strip().upper().replace("/", "")
            interval = combo.interval()
            path = Path(self.market_data_folder) / f"{symbol}_{interval}.csv"
            status = "available" if path.is_file() else "missing"
            self.direction_vote_htf_dataset.setText(f"{path}  [{status}]")
            supported = combo.value() in (1, 4, 24)
            self.direction_vote_htf_download.setEnabled(supported)
            if not supported:
                self.direction_vote_htf_dataset.setText(
                    f"{path}  [unsupported Binance interval — choose 1h, 4h, or 1d]"
                )

        def update_visibility(*_):
            visible = self.enable_direction_voting.isChecked() and self.direction_vote_use_htf.isChecked()
            layout.setRowVisible(combo, visible)
            layout.setRowVisible(self.direction_vote_htf_dataset, visible)
            layout.setRowVisible(self.direction_vote_htf_download, visible)

        def download_htf():
            if combo.value() not in (1, 4, 24):
                return
            if self.htf_download_dialog is not None:
                self.htf_download_dialog.show()
                self.htf_download_dialog.raise_()
                self.htf_download_dialog.activateWindow()
                return
            dialog = BinanceDownloadDialog(
                self,
                symbol=self.market_symbol.currentText(),
                strategy_timeframe=combo.interval(),
                intrabar_timeframe="1m",
                use_intrabar=False,
                data_folder=str(self.market_data_folder),
            )
            dialog.setWindowTitle("Download / Update Higher-Timeframe Dataset")
            self.htf_download_dialog = dialog

            def finished(_code, d=dialog):
                self.htf_download_dialog = None
                update_path()

            dialog.finished.connect(finished)
            dialog.show()

        combo.currentIndexChanged.connect(update_path)
        self.market_symbol.currentTextChanged.connect(update_path)
        self.direction_vote_htf_download.clicked.connect(download_htf)
        self.enable_direction_voting.toggled.connect(update_visibility)
        self.direction_vote_use_htf.toggled.connect(update_visibility)
        update_path()
        update_visibility()

    MainWindow.__init__ = patched_init
    MainWindow._binance_htf_ui_patch = True
