"""Composition-only read service for the future localhost browser API.

All operations delegate to pre-existing validated, read-only boundaries.
No research execution, filesystem writes, or catalog refresh are exposed.
"""
from pathlib import Path

from crypto_strategy_lab.browser_catalog import catalog_coverage, catalog_symbols
from crypto_strategy_lab.browser_completed_runs import read_completed_run
from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.gui.v2_controller import CatalogStatusService, GuiResearchRequest


class BrowserReadOnlyService:
    def __init__(self, catalog: CatalogStatusService):
        self._catalog = catalog

    def symbols(self, market="futures_um") -> list[str]:
        return catalog_symbols(self._catalog, market)

    def coverage(self, request: GuiResearchRequest) -> list[dict]:
        return catalog_coverage(self._catalog, request)

    def completed_run(self, run_dir: str | Path) -> dict:
        return read_completed_run(run_dir)

    def research_config(self, path: str | Path) -> dict:
        return read_research_config(path)
