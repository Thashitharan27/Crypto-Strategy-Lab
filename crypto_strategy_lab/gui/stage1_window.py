"""Stage-1 GUI shell that narrows the DI tab without changing engine/config behavior."""

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from .main_window import MainWindow as BaseMainWindow


class MainWindow(BaseMainWindow):
    """Use the current stable window while exposing only the intended DI controls."""

    def _build_di_strategy_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)

        direction_box = QGroupBox("DI Direction Selection")
        direction_form = QFormLayout(direction_box)
        rule = QLabel("Current Rule\n+DI above -DI → LONG\n-DI above +DI → SHORT")
        rule.setWordWrap(True)
        direction_form.addRow("", self.enable_di_direction_selection)
        direction_form.addRow("", rule)
        outer.addWidget(direction_box)

        pressure_box = QGroupBox("DI Pressure Analysis")
        pressure_form = QFormLayout(pressure_box)
        mode = QLabel("Analysis Mode: RECORD ONLY\nDoes not filter or reject trades.")
        help_text = QLabel(
            "DI chooses the initial LONG/SHORT direction. DI Pressure Analysis records "
            "whether directional pressure is strengthening or weakening. DI Spread "
            "filtering belongs in Strategy Profiles → Entry Rules."
        )
        help_text.setWordWrap(True)
        pressure_form.addRow("", self.enable_di_pressure_analysis)
        pressure_form.addRow("Lookback", self.di_pressure_lookback)
        pressure_form.addRow("", mode)
        pressure_form.addRow("", help_text)
        outer.addWidget(pressure_box)
        outer.addStretch(1)

        self.di_strategy_page = page
        self.config_controls += page.findChildren(QWidget)
        self.tabs.addTab(page, "DI Direction & Pressure")
        self.analysis_level.setCurrentText("Standard (Recommended)")
        self._apply_analysis_preset()
        self._set_analysis_advanced(False)
