"""Read-only bridge to the existing completed-run Strategy Visualizer.

This module does not own a new chart model, run reader, or HTTP session.
"""
from __future__ import annotations

from pathlib import Path


def load_browser_visualizer(
    application_service,
    completed_run_root: str | Path,
    run_id: str,
) -> object:
    """Load one verified run through the canonical desktop visualizer path.

    Input is a run *identifier*, never an arbitrary client filesystem path.
    The canonical reader verifies manifest and artifact references; the
    visualizer independently verifies its source/market-data dependencies.
    """
    if (
        not isinstance(run_id, str)
        or not 1 <= len(run_id) <= 100
        or not run_id.isascii()
        or not all(char.isalnum() or char in "_-" for char in run_id)
    ):
        raise ValueError("Invalid completed run ID")

    root = Path(completed_run_root).resolve()
    run_dir = root / run_id
    if run_dir.is_symlink():
        raise ValueError("Symlinked completed runs are not accepted")
    resolved = run_dir.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ValueError("Completed run not found")

    # Preserve the same authority used by the desktop launcher.
    manifest, _summary = application_service.completed_runs.read(resolved)
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    return CompletedRunVisualizer.load(application_service, resolved, manifest)
