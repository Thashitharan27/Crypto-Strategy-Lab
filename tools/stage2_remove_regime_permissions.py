"""One-shot Stage 2 cleanup for the obsolete global regime/direction permission layer."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LEGACY = (
    "enable_regime_direction_filter",
    "allow_bull_long",
    "allow_bull_short",
    "allow_bear_long",
    "allow_bear_short",
    "allow_sideways_long",
    "allow_sideways_short",
)


def edit(path: str, transform):
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after == before:
        print(f"no change: {path}")
    else:
        target.write_text(after, encoding="utf-8")
        print(f"updated: {path}")


def config(text: str) -> str:
    for name in LEGACY:
        text = re.sub(rf"^    {name}: bool = (?:False|True)\n", "", text, flags=re.M)
    text = text.replace(
        "if any((self.enable_regime_direction_filter, self.enable_directional_di_spread_range, self.enable_directional_adx_range, self.enable_directional_atr_pct_range, self.enable_directional_rsi_range, self.enable_directional_close_location_range, self.enable_directional_momentum_range)) and not self.enable_di_direction_sizing:",
        "if any((self.enable_directional_di_spread_range, self.enable_directional_adx_range, self.enable_directional_atr_pct_range, self.enable_directional_rsi_range, self.enable_directional_close_location_range, self.enable_directional_momentum_range)) and not self.enable_di_direction_sizing:",
    )
    return text


def config_logic(text: str) -> str:
    text = text.replace(
        '    "enable_regime_direction_filter": False, "allow_bull_long": True, "allow_bull_short": True, "allow_bear_long": True, "allow_bear_short": True, "allow_sideways_long": True, "allow_sideways_short": True,\n',
        '',
    )
    text = text.replace(
        '        enable_regime_direction_filter=bool(merged["enable_regime_direction_filter"]), allow_bull_long=bool(merged["allow_bull_long"]), allow_bull_short=bool(merged["allow_bull_short"]), allow_bear_long=bool(merged["allow_bear_long"]), allow_bear_short=bool(merged["allow_bear_short"]), allow_sideways_long=bool(merged["allow_sideways_long"]), allow_sideways_short=bool(merged["allow_sideways_short"]),\n',
        '',
    )
    return text


def engine(text: str) -> str:
    text = text.replace(
        '            if self.config.enable_regime_direction_filter:\n'
        '                if regime is None:\n'
        '                    return False, "Regime-direction filter warming up: market regime unavailable"\n'
        '                allowed = getattr(self.config, f"allow_{regime.lower()}_{direction.lower()}")\n'
        '                if not allowed:\n'
        '                    return False, f"{direction.title()} DI signal disabled in {regime.lower()} regime"\n',
        '',
    )
    text = text.replace(
        '{"regime_direction_filter_enabled":self.config.enable_regime_direction_filter,"directional_di_spread_range_enabled":',
        '{"directional_di_spread_range_enabled":',
    )
    return text


def main_window(text: str) -> str:
    text = text.replace('        self.enable_regime_direction_filter=QCheckBox("Enable Direction Permissions by Market Regime")\n', '')
    text = text.replace('        self.allow_bull_long=QCheckBox("Allow Bull Long"); self.allow_bull_long.setChecked(True); self.allow_bull_short=QCheckBox("Allow Bull Short"); self.allow_bull_short.setChecked(True)\n', '')
    text = text.replace('        self.allow_bear_long=QCheckBox("Allow Bear Long"); self.allow_bear_long.setChecked(True); self.allow_bear_short=QCheckBox("Allow Bear Short"); self.allow_bear_short.setChecked(True)\n', '')
    text = text.replace('        self.allow_sideways_long=QCheckBox("Allow Sideways Long"); self.allow_sideways_long.setChecked(True); self.allow_sideways_short=QCheckBox("Allow Sideways Short"); self.allow_sideways_short.setChecked(True)\n', '')
    text = text.replace('            ("",self.enable_regime_direction_filter),("",self.allow_bull_long),("",self.allow_bull_short),("",self.allow_bear_long),("",self.allow_bear_short),("",self.allow_sideways_long),("",self.allow_sideways_short),\n', '')
    text = text.replace(
        'values.update({"enable_regime_direction_filter":self.enable_regime_direction_filter.isChecked(),"allow_bull_long":self.allow_bull_long.isChecked(),"allow_bull_short":self.allow_bull_short.isChecked(),"allow_bear_long":self.allow_bear_long.isChecked(),"allow_bear_short":self.allow_bear_short.isChecked(),"allow_sideways_long":self.allow_sideways_long.isChecked(),"allow_sideways_short":self.allow_sideways_short.isChecked(),"enable_directional_di_spread_range":',
        'values.update({"enable_directional_di_spread_range":',
    )
    text = re.sub(
        r'^        for name in \("allow_bull_long","allow_bull_short","allow_bear_long","allow_bear_short","allow_sideways_long","allow_sideways_short"\): getattr\(self,name\)\.setChecked\(bool\(values\.get\(name,True\)\)\)\n',
        '', text, flags=re.M,
    )
    text = text.replace(
        'for name in ("enable_regime_direction_filter","enable_directional_di_spread_range","enable_directional_adx_range","enable_directional_atr_pct_range","enable_directional_rsi_range","enable_directional_close_location_range","enable_directional_momentum_range"):',
        'for name in ("enable_directional_di_spread_range","enable_directional_adx_range","enable_directional_atr_pct_range","enable_directional_rsi_range","enable_directional_close_location_range","enable_directional_momentum_range"):')
    return text


edit("crypto_strategy_lab/config.py", config)
edit("crypto_strategy_lab/gui/config_logic.py", config_logic)
edit("crypto_strategy_lab/engine.py", engine)
edit("crypto_strategy_lab/gui/main_window.py", main_window)

# Production code must have no stale reference to the removed layer.
for rel in (
    "crypto_strategy_lab/config.py",
    "crypto_strategy_lab/gui/config_logic.py",
    "crypto_strategy_lab/engine.py",
    "crypto_strategy_lab/gui/main_window.py",
):
    content = (ROOT / rel).read_text(encoding="utf-8")
    leftovers = [name for name in LEGACY if name in content]
    if leftovers:
        raise SystemExit(f"{rel}: stale legacy references remain: {leftovers}")
