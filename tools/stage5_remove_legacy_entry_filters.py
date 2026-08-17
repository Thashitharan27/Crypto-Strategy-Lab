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

def offsets(text):
    starts=[0]
    for i,ch in enumerate(text):
        if ch=="\n": starts.append(i+1)
    return starts

def pos(starts, lineno, col): return starts[lineno-1]+col

def expand_comma(text,a,b):
    # Prefer consuming a following comma; otherwise consume a preceding comma.
    j=b
    while j<len(text) and text[j] in " \t": j+=1
    if j<len(text) and text[j]==",":
        j+=1
        while j<len(text) and text[j] in " \t": j+=1
        return a,j
    i=a-1
    while i>=0 and text[i] in " \t": i-=1
    if i>=0 and text[i]==",": return i,b
    return a,b

def remove_ast_spans(text, spans):
    for a,b in sorted(set(spans), reverse=True): text=text[:a]+text[b:]
    return text

# config.py: remove dataclass fields and validation statements that refer to retired fields.
p="crypto_strategy_lab/config.py"; s=read(p); lines=s.splitlines(True); tree=ast.parse(s); cuts=[]
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in REMOVED:
        cuts.append((node.lineno-1,node.end_lineno))
    elif isinstance(node, ast.If):
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
s=re.sub(r"; self\.long_momentum_return_values=self\._trailing_return_hours_array\(config\.long_momentum_lookback_hours\)","",s)
write(p,s)

# config_logic.py: remove retired defaults and BacktestConfig keyword arguments using AST source spans.
p="crypto_strategy_lab/gui/config_logic.py"; s=read(p)
# First remove validation if-blocks that directly mention retired settings.
lines=s.splitlines(True); tree=ast.parse(s); cuts=[]
for node in ast.walk(tree):
    if isinstance(node,ast.If):
        seg="".join(lines[node.lineno-1:node.end_lineno])
        if any(name in seg for name in REMOVED): cuts.append((node.lineno-1,node.end_lineno))
for a,b in sorted(set(cuts), reverse=True): del lines[a:b]
s="".join(lines)
# Then remove dict entries and call keyword arguments precisely, preserving surrounding syntax.
tree=ast.parse(s); starts=offsets(s); spans=[]
for node in ast.walk(tree):
    if isinstance(node,ast.Dict):
        for key,val in zip(node.keys,node.values):
            if isinstance(key,ast.Constant) and isinstance(key.value,str) and key.value in REMOVED:
                a=pos(starts,key.lineno,key.col_offset); b=pos(starts,val.end_lineno,val.end_col_offset)
                spans.append(expand_comma(s,a,b))
    elif isinstance(node,ast.Call):
        for kw in node.keywords:
            if kw.arg in REMOVED:
                a=pos(starts,kw.value.lineno,kw.value.col_offset)-len(kw.arg)-1
                b=pos(starts,kw.value.end_lineno,kw.value.end_col_offset)
                spans.append(expand_comma(s,a,b))
s=remove_ast_spans(s,spans)
ast.parse(s)
write(p,s)

# main_window.py: remove dedicated widgets, groups, signal hookups, save/load statements.
p="crypto_strategy_lab/gui/main_window.py"; s=read(p)
s=remove_line_if_contains(s, REMOVED)
s=re.sub(r'\n\s*adx_box=QGroupBox\("Direction-Specific ADX"\).*?form\.addWidget\(adx_box\)\n', '\n', s, flags=re.S)
s=re.sub(r'\n\s*regime_box=QGroupBox\("Regime Entry Filters"\).*?form\.addWidget\(regime_box\)\n', '\n', s, flags=re.S)
ast.parse(s)
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

p="tests/test_stage5_legacy_entry_filters_removed.py"
write(p,'''from dataclasses import fields\nfrom pathlib import Path\n\nfrom crypto_strategy_lab.config import BacktestConfig\nfrom crypto_strategy_lab.gui.config_logic import DEFAULT_GUI_CONFIG\n\nREMOVED_FIELDS = '''+repr(REMOVED)+'''\n\ndef test_retired_oneoff_entry_filter_fields_are_gone():\n    names={f.name for f in fields(BacktestConfig)}\n    assert REMOVED_FIELDS.isdisjoint(names)\n    assert REMOVED_FIELDS.isdisjoint(DEFAULT_GUI_CONFIG)\n\ndef test_production_code_has_no_retired_oneoff_entry_filter_references():\n    root=Path(__file__).resolve().parents[1]\n    for rel in (\n        "crypto_strategy_lab/config.py",\n        "crypto_strategy_lab/engine.py",\n        "crypto_strategy_lab/gui/config_logic.py",\n        "crypto_strategy_lab/gui/main_window.py",\n    ):\n        text=(root/rel).read_text(encoding="utf-8")\n        for field in REMOVED_FIELDS:\n            assert field not in text, f"stale {field} reference in {rel}"\n''')
