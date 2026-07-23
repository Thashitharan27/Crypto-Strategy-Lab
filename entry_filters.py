"""Composable entry filter extension points."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from config import BacktestConfig, AdxFilterMode, BBWidthFilterMode, DISpreadFilterMode

@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: str

class EntryFilter:
    name = "Entry filter"
    def evaluate(self, i: int) -> FilterResult: return FilterResult(True, f"{self.name} disabled")

class ADXFilter(EntryFilter):
    name = "ADX filter"
    def __init__(self, config: BacktestConfig, adx_values): self.config=config; self.adx_values=adx_values
    def evaluate(self, i: int) -> FilterResult:
        if not self.config.enable_adx_filter or self.config.adx_filter_mode == AdxFilterMode.DISABLED:
            return FilterResult(True, "ADX filter disabled")
        value = float(self.adx_values[i]) if np.isfinite(self.adx_values[i]) else np.nan
        if not np.isfinite(value): return FilterResult(False, "ADX unavailable")
        mode = self.config.adx_filter_mode
        if mode == AdxFilterMode.MAXIMUM:
            ok = value <= self.config.adx_maximum; return FilterResult(ok, f"ADX {value:.2f} <= maximum {self.config.adx_maximum:g}" if ok else f"ADX {value:.2f} > maximum {self.config.adx_maximum:g}")
        if mode == AdxFilterMode.MINIMUM:
            ok = value >= self.config.adx_minimum; return FilterResult(ok, f"ADX {value:.2f} >= minimum {self.config.adx_minimum:g}" if ok else f"ADX {value:.2f} < minimum {self.config.adx_minimum:g}")
        ok = self.config.adx_minimum <= value <= self.config.adx_maximum
        return FilterResult(ok, f"minimum {self.config.adx_minimum:g} <= ADX {value:.2f} <= maximum {self.config.adx_maximum:g}" if ok else f"ADX {value:.2f} outside range {self.config.adx_minimum:g}-{self.config.adx_maximum:g}")

class BBWidthFilter(EntryFilter):
    name = "BB width filter"
    def __init__(self, config: BacktestConfig, values): self.config=config; self.values=values
    def evaluate(self, i: int) -> FilterResult:
        if not self.config.enable_bb_width_filter or self.config.bb_width_filter_mode == BBWidthFilterMode.DISABLED:
            return FilterResult(True, "BB width filter disabled")
        v = float(self.values[i]) if np.isfinite(self.values[i]) else np.nan
        if not np.isfinite(v): return FilterResult(False, "BB width unavailable")
        mode=self.config.bb_width_filter_mode; lo=self.config.bb_width_minimum; hi=self.config.bb_width_maximum
        if mode == BBWidthFilterMode.MAXIMUM:
            ok=v <= hi; return FilterResult(ok, f"BB width {v:.4f} <= maximum {hi:g}" if ok else f"BB width {v:.4f} > maximum {hi:g}")
        if mode == BBWidthFilterMode.MINIMUM:
            ok=v >= lo; return FilterResult(ok, f"BB width {v:.4f} >= minimum {lo:g}" if ok else f"BB width {v:.4f} < minimum {lo:g}")
        ok=lo <= v <= hi
        return FilterResult(ok, f"minimum {lo:g} <= BB width {v:.4f} <= maximum {hi:g}" if ok else f"BB width {v:.4f} outside range {lo:g}-{hi:g}")

class DISpreadFilter(EntryFilter):
    name = "DI spread filter"
    def __init__(self, config: BacktestConfig, values): self.config=config; self.values=values
    def evaluate(self, i: int) -> FilterResult:
        if not self.config.enable_di_spread_filter or self.config.di_spread_filter_mode == DISpreadFilterMode.DISABLED:
            return FilterResult(True, "DI spread filter disabled")
        v = float(self.values[i]) if np.isfinite(self.values[i]) else np.nan
        if not np.isfinite(v): return FilterResult(False, "DI spread unavailable")
        mode=self.config.di_spread_filter_mode; lo=self.config.di_spread_minimum; hi=self.config.di_spread_maximum
        if mode == DISpreadFilterMode.MAXIMUM:
            ok=v <= hi; return FilterResult(ok, f"DI spread {v:.2f} <= maximum {hi:g}" if ok else f"DI spread {v:.2f} > maximum {hi:g}")
        if mode == DISpreadFilterMode.MINIMUM:
            ok=v >= lo; return FilterResult(ok, f"DI spread {v:.2f} >= minimum {lo:g}" if ok else f"DI spread {v:.2f} < minimum {lo:g}")
        ok=lo <= v <= hi
        return FilterResult(ok, f"minimum {lo:g} <= DI spread {v:.2f} <= maximum {hi:g}" if ok else f"DI spread {v:.2f} outside range {lo:g}-{hi:g}")
