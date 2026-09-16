"""Crypto Strategy Lab application package."""

__version__ = "1.0.0"

# Make a securely stored OpenAI credential available to the existing SDK
# integration before CLI/GUI entry points construct any OpenAI clients.
from crypto_strategy_lab.openai_credentials import activate_openai_api_key

activate_openai_api_key()

# Install first-class strategy hooks before downstream modules import the
# strategy/runtime symbols by name. The installer is idempotent.
from crypto_strategy_lab.openai_strategy_install import install_openai_decision_strategy

install_openai_decision_strategy()
