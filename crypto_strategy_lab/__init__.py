"""Crypto Strategy Lab application package."""

__version__ = "1.0.0"

# Direction voting intentionally uses Binance's downloaded higher-timeframe
# candles rather than reconstructing them from the strategy dataset.
from crypto_strategy_lab.higher_timeframe_binance import install_binance_higher_timeframe_patch

install_binance_higher_timeframe_patch()

# Keep the main window source stable while layering the Binance HTF dataset
# controls onto it at import time.
try:
    from crypto_strategy_lab.gui.main_window import MainWindow
    from crypto_strategy_lab.gui.higher_timeframe_ui import install_higher_timeframe_ui

    install_higher_timeframe_ui(MainWindow)
except ImportError:
    # CLI/headless use must not require PySide6 GUI initialization.
    pass
