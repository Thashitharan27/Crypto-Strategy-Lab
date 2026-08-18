from PySide6.QtWidgets import QApplication, QGroupBox

from crypto_strategy_lab.gui.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def test_di_direction_pressure_tab_has_only_base_direction_and_pressure_sections():
    app()
    window = MainWindow()
    try:
        names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        page = window.tabs.widget(names.index("DI Direction & Pressure"))
        group_titles = [box.title() for box in page.findChildren(QGroupBox)]

        assert group_titles == ["DI Direction Selection", "DI Pressure Analysis"]
        assert page.isAncestorOf(window.enable_di_direction_selection)
        assert page.isAncestorOf(window.enable_di_pressure_analysis)
        assert page.isAncestorOf(window.di_pressure_lookback)
        assert window.di_pressure_lookback.minimum() == 1
        assert window.di_pressure_lookback.maximum() == 100
    finally:
        window.close()
