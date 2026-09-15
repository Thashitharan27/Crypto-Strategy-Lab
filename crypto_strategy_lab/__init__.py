"""Crypto Strategy Lab application package."""

__version__ = "1.0.0"

# Install first-class strategy hooks before downstream modules import the
# strategy/runtime symbols by name. The installer is idempotent.
from crypto_strategy_lab.openai_strategy_install import install_openai_decision_strategy

install_openai_decision_strategy()
