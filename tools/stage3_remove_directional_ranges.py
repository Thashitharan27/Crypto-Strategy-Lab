"""Remove legacy directional range filters now represented by Strategy Profiles."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LEGACY = (
    "enable_directional_di_spread_range",
    "directional_long_di_spread_minimum", "directional_long_di_spread_maximum",
    "directional_short_di_spread_minimum", "directional_short_di_spread_maximum",
    "enable_directional_adx_range",
    "directional_long_adx_minimum", "directional_long_adx_range_maximum",
    "directional_short_adx_range_minimum", "directional_short_adx_maximum",
    "enable_directional_atr_pct_range",
    "directional_long_atr_pct_minimum", "directional_long_atr_pct_maximum",
    "directional_short_atr_pct_minimum", "directional_short_atr_pct_maximum",
    "enable_directional_rsi_range", "directional_rsi_period",
    "directional_long_rsi_minimum", "directional_long_rsi_maximum",
    "directional_short_rsi_minimum", "directional_short_rsi_maximum",
    "enable_directional_close_location_range",
    "directional_long_close_location_minimum", "directional_long_close_location_maximum",
    "directional_short_close_location_minimum", "directional_short_close_location_maximum",
    "enable_directional_momentum_range", "directional_momentum_lookback_hours",
    "directional_long_momentum_minimum", "directional_long_momentum_maximum",
    "directional_short_momentum_minimum", "directional_short_momentum_maximum",
)


def edit(rel, fn):
    path = ROOT / rel
    before = path.read_text(encoding="utf-8")
    after = fn(before)
    path.write_text(after, encoding="utf-8")
    print(("updated: " if after != before else "no change: ") + rel)


def config(text):
    for name in LEGACY:
        text = re.sub(rf"^    {re.escape(name)}: [^\n]+\n", "", text, flags=re.M)
    text = re.sub(r'^        if any\(\(self\.enable_directional_di_spread_range.*?^        if not \(0 <= self\.directional_long_close_location_minimum <= 1.*?\n', '', text, flags=re.M | re.S)
    return text


def config_logic(text):
    lines=[]
    for line in text.splitlines(True):
        if line.startswith('    "enable_directional_') and any(name in line for name in LEGACY):
            continue
        lines.append(line)
    text=''.join(lines)
    for name in ("enable_directional_di_spread_range","enable_directional_adx_range","enable_directional_atr_pct_range","enable_directional_rsi_range","enable_directional_close_location_range","enable_directional_momentum_range"):
        text=re.sub(rf'^\s*{name}=bool\(merged\["{name}"\]\).*\n','',text,flags=re.M)
    return text


def engine(text):
    text=re.sub(r'; self\.directional_momentum_return_values=self\._trailing_return_hours_array\(config\.directional_momentum_lookback_hours\)','',text)
    text=re.sub(r'; self\.directional_rsi_values=rsi\(self\.close,config\.directional_rsi_period\)','',text)
    text=re.sub(r'^            if self\.config\.enable_directional_di_spread_range:.*?(?=^            if self\.config\.enable_bull_regime_short_filter:)','',text,flags=re.M|re.S)
    for key in ('"directional_di_spread_range_enabled":self.config.enable_directional_di_spread_range,','"directional_atr_pct_range_enabled":self.config.enable_directional_atr_pct_range,','"directional_rsi_range_enabled":self.config.enable_directional_rsi_range,','"directional_close_location_range_enabled":self.config.enable_directional_close_location_range,','"directional_momentum_range_enabled":self.config.enable_directional_momentum_range,'):
        text=text.replace(key,'')
    return text


def main_window(text):
    kept=[]
    for line in text.splitlines(True):
        if any(f'self.{name}=' in line for name in LEGACY):
            continue
        if any(f'self.{name}' in line for name in LEGACY) and 'directional_' in line:
            if 'values.update({' not in line and 'for name in (' not in line and 'getattr(self,name)' not in line:
                continue
        kept.append(line)
    text=''.join(kept)
    text=re.sub(r'values\.update\(\{"enable_directional_di_spread_range":self\.enable_directional_di_spread_range\.isChecked\(\),.*?"directional_short_momentum_maximum":parse_percentage\(self\.directional_short_momentum_maximum\.text\(\)\)\}\)','values.update({})',text,flags=re.S)
    text=re.sub(r'^\s*for name in \("enable_directional_di_spread_range".*?\n','',text,flags=re.M)
    text=re.sub(r'^\s*for name,default in \(\("directional_long_di_spread_minimum".*?\n','',text,flags=re.M)
    text=re.sub(r'^\s*for name,default in \(\("directional_long_adx_minimum".*?\n','',text,flags=re.M)
    text=re.sub(r'^\s*self\.directional_rsi_period\.setValue\(.*?\n','',text,flags=re.M)
    text=re.sub(r'^\s*for name,default in \(\("directional_long_atr_pct_minimum".*?\n','',text,flags=re.M)
    return text


def tests(text):
    return re.sub(r'^def test_directional_regime_and_indicator_ranges_filter_the_selected_side\(\):.*?(?=^def test_|\Z)','',text,flags=re.M|re.S)


edit("crypto_strategy_lab/config.py",config)
edit("crypto_strategy_lab/gui/config_logic.py",config_logic)
edit("crypto_strategy_lab/engine.py",engine)
edit("crypto_strategy_lab/gui/main_window.py",main_window)
edit("tests/test_backtester.py",tests)

for rel in ("crypto_strategy_lab/config.py","crypto_strategy_lab/gui/config_logic.py","crypto_strategy_lab/engine.py","crypto_strategy_lab/gui/main_window.py"):
    content=(ROOT/rel).read_text(encoding="utf-8")
    leftovers=[name for name in LEGACY if name in content]
    if leftovers:
        raise SystemExit(f"{rel}: stale directional-range references remain: {leftovers}")
