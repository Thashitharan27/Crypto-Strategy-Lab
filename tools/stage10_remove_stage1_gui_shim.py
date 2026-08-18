from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Make the base window own the final DI tab directly. The temporary stage1
# subclass only existed to override this section during the migration.
main = ROOT / "crypto_strategy_lab" / "gui" / "main_window.py"
text = main.read_text(encoding="utf-8")
old = '''        selection_box=QGroupBox("DI Direction Selection"); selection=QFormLayout(selection_box)\n        form.addWidget(selection_box)\n        direction_box=QGroupBox("Direction Selection"); direction_form=QFormLayout(direction_box)\n'''
new = '''        direction_box=QGroupBox("DI Direction Selection"); direction_form=QFormLayout(direction_box)\n'''
if old not in text:
    raise RuntimeError("Stage 10 expected duplicate DI direction groups were not found")
text = text.replace(old, new, 1)
if 'selection_box=QGroupBox("DI Direction Selection")' in text:
    raise RuntimeError("Stage 10 empty DI selection group remains")
if 'QGroupBox("Direction Selection")' in text:
    raise RuntimeError("Stage 10 duplicate Direction Selection title remains")
main.write_text(text, encoding="utf-8")

# Point the application and safety tests at the real main window instead of the
# transitional stage1 subclass.
replacements = {
    ROOT / "app.py": (
        "from crypto_strategy_lab.gui.stage1_window import MainWindow",
        "from crypto_strategy_lab.gui.main_window import MainWindow",
    ),
    ROOT / "tests" / "test_di_tab_stage1.py": (
        "from crypto_strategy_lab.gui.stage1_window import MainWindow",
        "from crypto_strategy_lab.gui.main_window import MainWindow",
    ),
    ROOT / "tests" / "test_stage2_regime_permissions_removed.py": (
        "from crypto_strategy_lab.gui.stage1_window import MainWindow",
        "from crypto_strategy_lab.gui.main_window import MainWindow",
    ),
}
for path, (before, after) in replacements.items():
    source = path.read_text(encoding="utf-8")
    if before not in source:
        raise RuntimeError(f"Stage 10 expected stage1 import not found in {path}")
    path.write_text(source.replace(before, after, 1), encoding="utf-8")

shim = ROOT / "crypto_strategy_lab" / "gui" / "stage1_window.py"
if not shim.exists():
    raise RuntimeError("Stage 10 expected stage1_window.py was not found")
shim.unlink()

regression = ROOT / "tests" / "test_stage10_stage1_gui_shim_removed.py"
regression.write_text('''from pathlib import Path\n\n\ndef test_stage1_gui_shim_is_removed_and_app_uses_main_window():\n    root = Path(__file__).resolve().parents[1]\n    assert not (root / "crypto_strategy_lab" / "gui" / "stage1_window.py").exists()\n    app_text = (root / "app.py").read_text(encoding="utf-8")\n    assert "gui.main_window import MainWindow" in app_text\n    assert "stage1_window" not in app_text\n\n\ndef test_base_main_window_owns_single_di_direction_group():\n    root = Path(__file__).resolve().parents[1]\n    text = (root / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")\n    assert 'QGroupBox("DI Direction Selection")' in text\n    assert 'selection_box=QGroupBox("DI Direction Selection")' not in text\n    assert 'QGroupBox("Direction Selection")' not in text\n\n\ndef test_safety_tests_no_longer_import_stage1_window():\n    root = Path(__file__).resolve().parents[1]\n    for rel in ("tests/test_di_tab_stage1.py", "tests/test_stage2_regime_permissions_removed.py"):\n        text = (root / rel).read_text(encoding="utf-8")\n        assert "gui.main_window import MainWindow" in text\n        assert "stage1_window" not in text\n''', encoding="utf-8")

print("Stage 10 stage1 GUI shim removed")
