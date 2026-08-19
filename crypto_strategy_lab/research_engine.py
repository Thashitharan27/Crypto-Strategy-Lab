"""Optional research hooks layered over the enhanced production engine."""
from __future__ import annotations

from crypto_strategy_lab.dual_entry_research import store_pending
from crypto_strategy_lab.dual_entry_research_fast import run_dual_entry_research
from crypto_strategy_lab.enhanced_engine import EnhancedBacktestEngine


class ResearchBacktestEngine(EnhancedBacktestEngine):
    """Enhanced engine plus removable post-run research simulations."""

    def run(self):
        trades = super().run()
        if bool(getattr(self.config, "enable_dual_entry_research", False)):
            observations, di_summary, summary = run_dual_entry_research(self)
            store_pending(self.config, observations, di_summary, summary)
        return trades
