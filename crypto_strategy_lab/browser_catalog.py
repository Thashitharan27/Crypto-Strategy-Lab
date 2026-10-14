"""Read-only browser catalog surface; reuse the existing GUI catalog service.

This module neither refreshes archives nor executes research.
"""
from crypto_strategy_lab.gui.v2_controller import CatalogStatusService, GuiResearchRequest


def catalog_symbols(catalog: CatalogStatusService, market="futures_um") -> list[str]:
    return catalog.symbols(market)


def catalog_coverage(catalog: CatalogStatusService, request: GuiResearchRequest) -> list[dict]:
    return catalog.coverage(request)
