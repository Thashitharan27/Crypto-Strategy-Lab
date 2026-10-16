"""Composition-only read service for the future localhost browser API.

All operations delegate to pre-existing validated, read-only boundaries.
No research execution, filesystem writes, or catalog refresh are exposed.
"""
from pathlib import Path

from crypto_strategy_lab.browser_capabilities import browser_capabilities
from crypto_strategy_lab.browser_catalog import catalog_coverage, catalog_symbols
from crypto_strategy_lab.browser_completed_runs import read_completed_run
from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.gui.v2_controller import (
    CatalogStatusService,
    GuiApplicationService,
    GuiResearchRequest,
)
from crypto_strategy_lab.paths import resolve_data_lake_runtime_paths


class BrowserReadOnlyService:
    def __init__(self, catalog: CatalogStatusService, application_service=None):
        self._catalog = catalog
        self.application_service = application_service

    def symbols(self, market="futures_um") -> list[str]:
        return catalog_symbols(self._catalog, market)

    def coverage(self, request: GuiResearchRequest) -> list[dict]:
        return catalog_coverage(self._catalog, request)

    def completed_run(self, run_dir: str | Path) -> dict:
        return read_completed_run(run_dir)

    def research_config(self, path: str | Path) -> dict:
        return read_research_config(path)

    def portfolio_candidates(self, output_root: str | Path) -> list[dict]:
        """Discover verified completed resilience runs; never replay or expose paths."""
        from crypto_strategy_lab.portfolio_replay import discover_resilience_runs

        rows = discover_resilience_runs(output_root)
        return [
            {
                "run_id": row["run_id"],
                "run_folder_id": Path(row["run_dir"]).name,
                "symbol": row["symbol"],
                "strategy_timeframe": row.get("strategy_timeframe"),
                "candidate_rows": row["candidate_rows"],
                "completed_at": row.get("completed_at"),
                "sampling_mode": row["sampling_mode"],
            }
            for row in rows
        ]

    def capabilities(self) -> dict:
        return browser_capabilities()


def build_browser_readonly_service(
    *,
    raw_root: str | Path | None = None,
    cache_root: str | Path | None = None,
) -> BrowserReadOnlyService:
    """Compose the browser facade from the existing desktop application service.

    Browser migration must not construct a second catalog, loader or cache
    implementation. This helper resolves the same Data Lake roots as the desktop
    process, instantiates the existing GuiApplicationService, and exposes only
    its read-only catalog facade.
    """

    paths = resolve_data_lake_runtime_paths()
    application = GuiApplicationService(
        Path(raw_root) if raw_root is not None else paths.raw_root,
        Path(cache_root) if cache_root is not None else paths.cache_root,
    )
    return BrowserReadOnlyService(application.catalog, application_service=application)
