"""Execution engine adapter for the Data Lake v2 pipeline.

The legacy ``BacktestEngine`` still contains historical file-loading behavior for
structural regimes. This adapter is the forward path: all market data is injected
by the caller and the simulator never resolves benchmark filenames itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.features.market_regime import structural_regime_values


class DataLakeBacktestEngine(BacktestEngine):
    """BacktestEngine with market regime supplied from prepared Data Lake inputs."""

    def __init__(self, *args, structural_benchmark: pd.DataFrame | None = None, **kwargs):
        self.structural_benchmark = structural_benchmark
        super().__init__(*args, **kwargs)

    def _market_regime_array(self):
        if self.config.market_regime_method == "ASSET_RETURN":
            threshold = abs(float(self.config.bull_regime_return_threshold))
            return np.array(
                [
                    None
                    if not np.isfinite(value)
                    else (
                        "BULL"
                        if value >= threshold
                        else ("BEAR" if value <= -threshold else "SIDEWAYS")
                    )
                    for value in self.bull_regime_return_values
                ],
                dtype=object,
            )

        if self.structural_benchmark is None or self.structural_benchmark.empty:
            label = "Asset" if self.config.market_regime_method == "ASSET_STRUCTURAL" else "BTC"
            raise ValueError(
                f"{label} structural regime requires a prepared Data Lake benchmark frame"
            )

        return structural_regime_values(
            self.times,
            self.structural_benchmark,
            sma_days=int(self.config.structural_regime_sma_days),
            slope_lookback_days=int(self.config.structural_regime_slope_lookback_days),
        )
