from pathlib import Path


def test_stage1_gui_shim_is_removed_and_app_uses_v2_main_window():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "crypto_strategy_lab" / "gui" / "stage1_window.py").exists()
    app_text = (root / "app.py").read_text(encoding="utf-8")
    assert "gui.v2_main_window import MainWindow" in app_text
    assert "gui.data_lake_main_window import MainWindow" not in app_text
    assert "stage1_window" not in app_text


def test_base_main_window_owns_single_di_direction_group():
    root = Path(__file__).resolve().parents[1]
    text = (root / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")
    assert 'QGroupBox("DI Direction Selection")' in text
    assert 'selection_box=QGroupBox("DI Direction Selection")' not in text
    assert 'QGroupBox("Direction Selection")' not in text


def test_safety_tests_no_longer_import_stage1_window():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "tests" / "test_di_tab_stage1.py").exists()
    text = (root / "tests" / "test_stage2_regime_permissions_removed.py").read_text(encoding="utf-8")
    assert "gui.main_window import MainWindow" in text
    assert "stage1_window" not in text
