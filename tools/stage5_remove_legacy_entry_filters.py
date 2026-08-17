from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]

REMOVED = {
    "enable_directional_adx_filter","directional_long_adx_maximum","directional_short_adx_minimum",
    "enable_long_momentum_filter","long_momentum_lookback_hours","long_momentum_minimum_return",
    "enable_biased_short_adx_cap","biased_short_adx_maximum",
    "enable_short_vwap_distance_filter","short_vwap_minimum_distance_atr",
    "enable_bull_regime_short_filter",
    "enable_bear_regime_adx_filter","bear_regime_adx_minimum",
}
ENABLE_MARKERS = {
    "enable_directional_adx_filter","enable_long_momentum_filter","enable_biased_short_adx_cap",
    "enable_short_vwap_distance_filter","enable_bull_regime_short_filter","enable_bear_regime_adx_filter",
}

def read(rel): return (ROOT/rel).read_text(encoding="utf-8")
def write(rel, text): (ROOT/rel).write_text(text, encoding="utf-8")

def remove_line_if_contains(text, markers):
    return "".join(line for line in text.splitlines(True) if not any(m in line for m in markers))

# config.py: remove dataclass fields and validation statements that refer to retired fields.
p="crypto_strategy_lab/config.py"; s=read(p); lines=s.splitlines(True); tree=ast.parse(s); cuts=[]
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in REMOVED:
        cuts.append((node.lineno-1,node.end_lineno))
    elif isinstance(node, ast.If):
        segment="".join(lines[node.lineno-1:node.end_lineno])
        if any(name in segment for name in REMOVED): cuts.append((node.lineno-1,node.end_lineno))
# also remove simple validation statements containing removed fields
for node in ast.walk(tree):
    if isinstance(node,(ast.Expr,ast.Assign,ast.AnnAssign)):
        segment="".join(lines[node.lineno-1:node.end_lineno])
        if any(name in segment for name in REMOVED): cuts.append((node.lineno-1,node.end_lineno))
for a,b in sorted(set(cuts), reverse=True): del lines[a:b]
write(p,"".join(lines))

# engine.py: remove the six legacy conditional entry-filter blocks using AST line ranges.
p="crypto_strategy_lab/engine.py"; s=read(p); lines=s.splitlines(True); tree=ast.parse(s); cuts=[]
for node in ast.walk(tree):
    if isinstance(node,ast.If):
        test=ast.get_source_segment(s,node.test) or ""
        if any(marker in test for marker in ENABLE_MARKERS): cuts.append((node.lineno-1,node.end_lineno))
for a,b in sorted(set(cuts), reverse=True): del lines[a:b]
s="".join(lines)
# remove obsolete precomputed legacy momentum series from the dense __init__ line
s=re.sub(r"; self\.long_momentum_return_values=self\._trailing_return_hours_array\(config\.long_momentum_lookback_hours\)","",s)
write(p,s)

# config_logic.py: defaults/serialization are one-entry-per-line or dense dict entries; remove exact key/value pairs.
p="crypto_strategy_lab/gui/config_logic.py"; s=read(p)
for name in REMOVED:
    s=re.sub(rf'\s*["\']{re.escape(name)}["\']\s*:\s*[^,}}]+,?', '', s)
    s=re.sub(rf'\s*{re.escape(name)}\s*=\s*[^,\n)]+,?', '', s)
write(p,s)

# main_window.py: remove dedicated widgets, groups, signal hookups, save/load statements.
p="crypto_strategy_lab/gui/main_window.py"; s=read(p)
# Dedicated one-line widget declarations / signal hookups / value save-load statements.
s=remove_line_if_contains(s, REMOVED)
# Remove now-empty legacy group blocks by exact titles through the next form.addWidget.
s=re.sub(r'\n\s*adx_box=QGroupBox\("Direction-Specific ADX"\).*?form\.addWidget\(adx_box\)\n', '\n', s, flags=re.S)
s=re.sub(r'\n\s*regime_box=QGroupBox\("Regime Entry Filters"\).*?form\.addWidget\(regime_box\)\n', '\n', s, flags=re.S)
write(p,s)

# tests: remove tests that directly exercise the retired one-off filters.
for p in ["tests/test_gui_config_logic.py","tests/test_gui_main_window.py","tests/test_coin_flip_sizing.py","tests/test_backtester.py"]:
    path=ROOT/p
    if not path.exists(): continue
    s=read(p); lines=s.splitlines(True)
    try: tree=ast.parse(s)
    except SyntaxError: continue
    cuts=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            seg="".join(lines[node.lineno-1:node.end_lineno])
            if any(name in seg for name in REMOVED): cuts.append((node.lineno-1,node.end_lineno))
    for a,b in sorted(cuts, reverse=True): del lines[a:b]
    write(p,"".join(lines))

# Regression test.
p="tests/test_stage5_legacy_entry_filters_removed.py"
write(p,'''from dataclasses import fields\nfrom pathlib import Path\n\nfrom crypto_strategy_lab.config import BacktestConfig\nfrom crypto_strategy_lab.gui.config_logic import DEFAULT_GUI_CONFIG\n\nREMOVED_FIELDS = '''+repr(REMOVED)+'''\n\ndef test_retired_oneoff_entry_filter_fields_are_gone():\n    names={f.name for f in fields(BacktestConfig)}\n    assert REMOVED_FIELDS.isdisjoint(names)\n    assert REMOVED_FIELDS.isdisjoint(DEFAULT_GUI_CONFIG)\n\ndef test_production_code_has_no_retired_oneoff_entry_filter_references():\n    root=Path(__file__).resolve().parents[1]\n    for rel in (\n        "crypto_strategy_lab/config.py",\n        "crypto_strategy_lab/engine.py",\n        "crypto_strategy_lab/gui/config_logic.py",\n        "crypto_strategy_lab/gui/main_window.py",\n    ):\n        text=(root/rel).read_text(encoding="utf-8")\n        for field in REMOVED_FIELDS:\n            assert field not in text, f"stale {field} reference in {rel}"\n''')
