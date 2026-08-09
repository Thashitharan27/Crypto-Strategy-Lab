"""Crypto Strategy Lab application package."""

__version__ = "1.0.0"

# Direction voting intentionally uses Binance's downloaded higher-timeframe
# candles rather than reconstructing them from the strategy dataset.
from crypto_strategy_lab.higher_timeframe_binance import install_binance_higher_timeframe_patch

install_binance_higher_timeframe_patch()
