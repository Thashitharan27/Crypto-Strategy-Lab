"""PySide6 desktop GUI for the long/short crypto backtester."""

# The core installer extends DIRECTION_MODES before this package is imported.
# Patch the researcher-facing label once so RuleStrategyBuilder can render the
# new mode without changing any existing strategy labels.
from crypto_strategy_lab.ai_decision import OPENAI_DECISION_MODE
from crypto_strategy_lab.gui import rule_strategy_builder as _rule_strategy_builder

_rule_strategy_builder.DIRECTION_LABELS.setdefault(
    OPENAI_DECISION_MODE,
    "AI Decision — OpenAI",
)
